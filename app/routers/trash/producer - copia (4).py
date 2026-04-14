from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional, List

from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel, Field, root_validator
from starlette.responses import JSONResponse

from app.db import get_conn

from psycopg.rows import dict_row
# -------------------------------------------------------------------
# DB utils
# -------------------------------------------------------------------
def _table_columns(conn, table: str, schema: str = "public") -> set[str]:
    """Devuelve set de columnas existentes para (schema.table). Cache simple por proceso."""
    key = f"{schema}.{table}"
    if not hasattr(_table_columns, "_cache"):
        _table_columns._cache = {}
    cache = _table_columns._cache
    if key in cache:
        return cache[key]
    cur = conn.execute(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = %s AND table_name = %s
        """,
        (schema, table),
    )
    rows = cur.fetchall()
    cols = set()
    for r in rows:
        if isinstance(r, dict):
            v = r.get('column_name') or next(iter(r.values()), None)
        else:
            try:
                v = r[0]
            except Exception:
                v = getattr(r, 'column_name', None)
        if v:
            cols.add(str(v))

    cache[key] = cols
    return cols


# -------------------------------------------------------------------
# Dashboard scoping helpers (schema-safe)
# -------------------------------------------------------------------
def _has_col(cols: set[str], *names: str) -> Optional[str]:
    """Return first existing column name among candidates."""
    for n in names:
        if n in cols:
            return n
    return None


def _scope_where_for_orders(conn, producer_slug: str, tenant_id: str) -> tuple[str, tuple]:
    """Build a WHERE predicate to scope orders to the event owner (producer).

    Preference:
      1) orders.producer_tenant == producer_slug (new unified flow)
      2) orders.tenant == producer_slug (older shared-core contract)
      3) orders.tenant_id == tenant_id (fallback; weaker but keeps older envs working)
    """
    cols = _table_columns(conn, "orders")
    col = _has_col(cols, "producer_tenant", "tenant", "producer")
    if col:
        return f"o.{col} = %s", (producer_slug,)
    col2 = _has_col(cols, "tenant_id")
    if col2:
        return f"o.{col2} = %s", (tenant_id,)
    return "TRUE", ()


def _scope_where_for_tickets(conn, producer_slug: str, tenant_id: str) -> tuple[str, tuple]:
    cols = _table_columns(conn, "tickets")
    col = _has_col(cols, "producer_tenant", "tenant", "producer")
    if col:
        return f"t.{col} = %s", (producer_slug,)
    col2 = _has_col(cols, "tenant_id")
    if col2:
        return f"t.{col2} = %s", (tenant_id,)
    return "TRUE", ()


def _orders_join_exprs() -> tuple[str, str]:
    """Return (orders_key_expr, order_items_fk_expr)."""
    # In shared contract, order_items.order_id references the order id (string).
    # In our unified flow, we store UUID in orders.id and order_items.order_id as text UUID.
    return "o.id::text", "oi.order_id"


router = APIRouter()

def _require_auth(request: Request) -> dict:
    """Auth dependency for producer routes.

    Accepts either:
      - a logged-in session (request.session['user'])
      - or a debug header 'x-producer' (useful for local/dev testing)
    """
    # Debug/local shortcut
    hdr = (request.headers.get('x-producer') or '').strip()
    if hdr:
        return {'producer': _norm_id(hdr), 'auth': 'header'}

    # Normal path: session-based auth
    user = None
    if hasattr(request, 'session'):
        user = request.session.get('user') or request.session.get('profile')

    if not user:
        raise HTTPException(status_code=401, detail='not_authenticated')

    # Ensure we have a producer slug (fallback to email/localpart if present)
    producer = user.get('producer') if isinstance(user, dict) else None
    if not producer and isinstance(user, dict):
        email = user.get('email') or user.get('preferred_username')
        if isinstance(email, str) and '@' in email:
            producer = email.split('@', 1)[0]
    if not producer and isinstance(user, dict):
        producer = user.get('sub') or user.get('id')
    if producer:
        user['producer'] = _norm_id(str(producer))

    return user if isinstance(user, dict) else {'user': user}

from fastapi import UploadFile, File
import pathlib

def _uploads_dir() -> str:
    d = os.getenv("UPLOAD_DIR", "static/uploads")
    os.makedirs(d, exist_ok=True)
    return d

@router.post("/upload/flyer")
async def upload_flyer(request: Request, file: UploadFile = File(...)):
    """
    Sube flyer del evento (demo).
    Devuelve URL pública servida por /uploads.
    """
    # Requiere login productor
    _ = _require_auth(request)  # 401 si no hay sesión (o x-producer)

    if not file.filename:
        raise HTTPException(status_code=400, detail="file_required")

    # Limit demo: 6MB
    content = await file.read()
    if len(content) > 6 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="file_too_large")

    ext = pathlib.Path(file.filename).suffix.lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        raise HTTPException(status_code=400, detail="invalid_file_type")

    fname = f"flyer_{uuid.uuid4().hex}{ext}"
    path = os.path.join(_uploads_dir(), fname)
    with open(path, "wb") as f:
        f.write(content)

    return {"ok": True, "url": f"/static/uploads/{fname}"}



# -------------------------------------------------------------------
# Helpers (tenant/producer). Hasta que haya auth real, usamos defaults.
# -------------------------------------------------------------------
def _tenant_from_request(request: Request) -> str:
    # Header primero: permite que el frontend fuerce el tenant activo sin pelearse con session.
    ht = request.headers.get("x-tenant")
    if isinstance(ht, str) and ht.strip():
        return _norm_id(ht, default="default")
    t = (request.session.get("tenant") if hasattr(request, "session") else None) or "default"
    return _norm_id(str(t), default="default")


def _producer_from_request(request: Request) -> str:
    """Resuelve el producer efectivo.

    Regla: **Header primero** (x-producer), luego session.

    Motivo: la session puede guardar un objeto/label (p.ej. 'Ger', 'Germán', email),
    mientras que en DB el producer histórico quedó como 'ger'. Si priorizamos header
    y normalizamos, el listado y el create/update se comportan igual en PC y móvil.
    """
    hp = request.headers.get("x-producer")
    if isinstance(hp, str) and hp.strip():
        return _norm_id(hp, default="ger")

    p: Any = None
    if hasattr(request, "session"):
        sp = request.session.get("producer")
        if isinstance(sp, str) and sp.strip():
            p = sp.strip()
        elif isinstance(sp, dict):
            for k in ("slug", "handle", "username", "name", "email", "id", "producer"):
                v = sp.get(k)
                if isinstance(v, str) and v.strip():
                    p = v.strip()
                    break

    return _norm_id(str(p), default="ger")






def _table_column_types(conn, table: str, schema: str = "public") -> dict[str, str]:
    """Devuelve mapping columna -> data_type (information_schema). Cache simple por proceso."""
    key = f"{schema}.{table}"
    if not hasattr(_table_column_types, "_cache"):
        _table_column_types._cache = {}
    cache = _table_column_types._cache
    if key in cache:
        return cache[key]
    cur = conn.execute(
        """
        SELECT column_name, data_type
          FROM information_schema.columns
         WHERE table_schema = %s AND table_name = %s
        """,
        (schema, table),
    )
    rows = cur.fetchall()
    out: dict[str, str] = {}
    for r in rows:
        if isinstance(r, dict):
            name = r.get("column_name") or (list(r.values())[0] if r else None)
            dtype = r.get("data_type") or (list(r.values())[1] if len(r.values()) > 1 else None)
        else:
            name = r[0] if len(r) > 0 else None
            dtype = r[1] if len(r) > 1 else None
        if name:
            out[str(name)] = str(dtype or "")
    cache[key] = out
    return out

def _smart_now_for_column(col_type: str):
    """Retorna valor 'ahora' compatible con el tipo de columna."""
    t = (col_type or "").lower()
    # timestamps/dates
    if "timestamp" in t or "date" in t or "time" in t:
        return datetime.now(timezone.utc)
    # numeric epoch (int/bigint)
    if "int" in t or "numeric" in t or "double" in t or "real" in t or "decimal" in t:
        return _now_epoch_s()
    # default: no value (let DB default work) by returning None
    return None

def _now_epoch_s() -> int:
    return int(datetime.utcnow().timestamp())


def _coerce_bool(v: Any, default: bool = True) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("1", "true", "t", "yes", "y", "on"):
        return True
    if s in ("0", "false", "f", "no", "n", "off"):
        return False
    return default



import re
import unicodedata

def _norm_id(s: str, default: str = "ger") -> str:
    """Normaliza ids tipo producer/tenant a un formato estable."""
    if not isinstance(s, str):
        return default
    s = s.strip().lower()
    if not s:
        return default
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[^a-z0-9_-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or default

# -------------------------------------------------------------------
# Schemas
# -------------------------------------------------------------------
class EventCreateIn(BaseModel):
    title: str = Field(..., min_length=1)
    date_text: Optional[str] = None
    city: Optional[str] = None
    venue: Optional[str] = None
    description: Optional[str] = None
    accept_terms: bool = False
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None

    # Flyer: si tu frontend guarda URL en una columna (p.ej. flyer_url) ajustá abajo.
    flyer_url: Optional[str] = None

    # Mapa/ubicación
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None

    # UI
    hero_bg: Optional[str] = None


class EventUpdateIn(BaseModel):
    # Todo opcional para permitir edición parcial (PUT manda el objeto completo desde el front,
    # pero no obligamos a todos los campos en el backend).
    title: Optional[str] = None
    slug: Optional[str] = None
    date_text: Optional[str] = None
    city: Optional[str] = None
    venue: Optional[str] = None
    description: Optional[str] = None
    flyer_url: Optional[str] = None
    hero_bg: Optional[str] = None
    uber_link: Optional[str] = None
    accept_terms: Optional[bool] = None
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class EventToggleIn(BaseModel):
    slug: str = Field(..., min_length=1)
    active: int = Field(..., ge=0, le=1)


class SaleItemUpsertIn(BaseModel):
    event_slug: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    kind: str = Field(default="ticket", min_length=1)

    # Compat: frontend puede mandar price (ARS) y stock
    price: Optional[float] = None
    stock: Optional[int] = None

    price_cents: int = Field(default=0, ge=0)
    stock_total: int = Field(default=0, ge=0)

    start_date: Optional[str] = None  # "YYYY-MM-DD" o None
    end_date: Optional[str] = None

    active: bool = Field(default=True)
    sort_order: int = Field(default=0, ge=0)



    @root_validator(pre=True)
    def _compat_price_stock(cls, values):
        # price en unidades (ej: 3500.5) -> price_cents
        if ('price_cents' not in values) or (values.get('price_cents') is None) or (values.get('price_cents') == 0 and values.get('price') not in (None, 0, '0', 0.0)):
            p = values.get('price')
            if p is not None:
                try:
                    values['price_cents'] = int(round(float(p) * 100))
                except Exception:
                    pass
        # stock -> stock_total
        if ('stock_total' not in values) or (values.get('stock_total') is None) or (values.get('stock_total') == 0 and values.get('stock') not in (None, 0, '0')):
            s = values.get('stock')
            if s is not None:
                try:
                    values['stock_total'] = int(s)
                except Exception:
                    pass
        return values

class SaleItemToggleIn(BaseModel):
    id: int
    active: int = Field(..., ge=0, le=1)


class SellerUpsertIn(BaseModel):
    event_slug: str = Field(..., min_length=1)
    code: str = Field(..., min_length=1)  # código corto (ej: "vendedor1")
    name: str = Field(..., min_length=1)
    active: bool = Field(default=True)


class SellerToggleIn(BaseModel):
    id: int
    active: int = Field(..., ge=0, le=1)


# -------------------------------------------------------------------
# Identity (no hardcode en frontend)
# -------------------------------------------------------------------
@router.get("/me")
def api_me(request: Request):
    tenant_id = _tenant_from_request(request)
    producer = _producer_from_request(request)
    tenant = producer

    user = None
    if hasattr(request, "session"):
        sp = request.session.get("producer")
        if isinstance(sp, dict):
            user = {
                "id": sp.get("id"),
                "name": sp.get("name"),
                "email": sp.get("email"),
            }

    return JSONResponse({"ok": True, "tenant_id": tenant_id,
            "tenant": tenant, "producer": producer, "user": user})


# -------------------------------------------------------------------
# Events
# -------------------------------------------------------------------
@router.get("/events")
def api_producer_events(request: Request, user: dict = Depends(_require_auth)):
    """Devuelve SOLO eventos del productor autenticado."""
    tenant_id = _tenant_from_request(request)

    # Fuente de verdad: el productor autenticado.
    producer = (user or {}).get("producer")
    if not producer:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Normalizamos y persistimos en sesión para que el frontend tenga un valor estable.
    request.session["producer"] = producer
    tenant = producer

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT slug, title, date_text, city, venue, active, hero_bg
            FROM events
            WHERE tenant_id = %s AND tenant = %s
            ORDER BY created_at DESC
            LIMIT 200
            """,
            (tenant_id, producer),
        ).fetchall()

    events = [
        {
            "slug": r["slug"],
            "title": r["title"],
            "date_text": r.get("date_text"),
            "city": r.get("city"),
            "venue": r.get("venue"),
            "active": bool(r.get("active", True)),
            "hero_bg": r.get("hero_bg"),
        }
        for r in rows
    ]
    return JSONResponse(content=events)


# Alias para compatibilidad (algunos builds llaman /api/producer/events/mine)
@router.get("/events/mine")
def api_producer_events_mine(request: Request, user: dict = Depends(_require_auth)):
    return api_producer_events(request, user=user)


@router.get("/dashboard")
def api_producer_dashboard(
    request: Request,
    tenant_id: str = "default",
    event_slug: str = "",
    user=Depends(_require_auth),
):
    """
    Producer dashboard for a given event.

    Importante:
    - La visibilidad del productor NO depende del comprador.
    - Se atribuye por el dueño del evento (events.tenant / producer_slug).
    - El frontend (App.jsx) espera:
        - kpis: { total, bar, tickets, avg }
        - timeSeries: [{hour, bar, tickets}]
        - topProducts: [{name, sales, revenue, category}]
    """
    warnings = []

    tenant_id = _norm_id(tenant_id, default=_tenant_from_request(request))
    event_slug = (event_slug or "").strip().lower()
    if not event_slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")

    with get_conn() as conn:
        cur = conn.cursor(row_factory=dict_row)

        # ---- Load event (no depender de tenant_id=default) ----
        cur.execute(
            """
            SELECT slug, title, date_text, city, venue, flyer_url, active, tenant, tenant_id
            FROM events
            WHERE tenant_id = %s AND slug = %s
            LIMIT 1
            """,
            (tenant_id, event_slug),
        )
        ev = cur.fetchone()

        if not ev:
            cur.execute(
                """
                SELECT slug, title, date_text, city, venue, flyer_url, active, tenant, tenant_id
                FROM events
                WHERE slug = %s
                LIMIT 1
                """,
                (event_slug,),
            )
            ev = cur.fetchone()
            if ev:
                warnings.append("event_loaded_by_slug_only")

        if not ev:
            raise HTTPException(status_code=404, detail="event_not_found")

        producer_slug = (ev.get("tenant") or "").strip()
        if not producer_slug:
            raise HTTPException(status_code=500, detail="event_missing_producer_tenant")

        # ---- Sale items (catalog) ----
        cur.execute(
            """
            SELECT id, tenant, event_slug, name, kind, price_cents, stock_total, stock_sold, active, display_order
            FROM sale_items
            WHERE tenant = %s AND event_slug = %s
            ORDER BY display_order, id
            """,
            (producer_slug, event_slug),
        )
        items = cur.fetchall() or []

        # ---- Scope for orders ----
        where_orders, args_scope_orders = _scope_where_for_orders(conn, producer_slug, tenant_id)

        # ---- KPIs ----
        orders_paid = 0
        revenue_cents = 0

        try:
            cur.execute(
                f"""
                SELECT
                  COUNT(*) FILTER (WHERE status ILIKE 'PAID') AS orders_paid,
                  COALESCE(
                    SUM(
                      COALESCE(total_cents, ROUND(total_amount * 100)::bigint)
                    ) FILTER (WHERE status ILIKE 'PAID'),
                    0
                  ) AS revenue_cents
                FROM orders o
                WHERE {where_orders}
                  AND o.event_slug = %s
                """,
                (*args_scope_orders, event_slug),
            )
            rr = cur.fetchone() or {}
            orders_paid = int(rr.get("orders_paid") or 0)
            revenue_cents = int(rr.get("revenue_cents") or 0)
        except Exception as e:
            warnings.append(f"orders_kpi_failed:{type(e).__name__}")

        # ---- Bar revenue (por source='bar' o bar_slug) ----
        bar_cents = 0
        try:
            cur.execute(
                f"""
                SELECT COALESCE(
                  SUM(COALESCE(total_cents, ROUND(total_amount * 100)::bigint))
                  FILTER (WHERE status ILIKE 'PAID'),
                  0
                ) AS bar_cents
                FROM orders o
                WHERE {where_orders}
                  AND o.event_slug = %s
                  AND (
                        COALESCE(o.source,'') = 'bar'
                     OR o.bar_slug IS NOT NULL
                     OR COALESCE(o.order_kind,'') ILIKE 'bar'
                     OR COALESCE(o.kind,'') ILIKE 'bar'
                  )
                """,
                (*args_scope_orders, event_slug),
            )
            rb = cur.fetchone() or {}
            bar_cents = int(rb.get("bar_cents") or 0)
        except Exception as e:
            warnings.append(f"bar_kpi_failed:{type(e).__name__}")

        # ---- Tickets sold (prefer tickets table, fallback order_items) ----
        sold_qty = 0

        # 1) tickets table (es lo más “real” para emitidos)
        try:
            where_t, args_scope_t = _scope_where_for_tickets(conn, producer_slug, tenant_id)
            cur.execute(
                f"""
                SELECT COUNT(*)::bigint AS sold_qty
                FROM tickets t
                WHERE {where_t}
                  AND t.event_slug = %s
                  AND COALESCE(t.status,'') NOT ILIKE 'revoked'
                """,
                (*args_scope_t, event_slug),
            )
            rt = cur.fetchone() or {}
            sold_qty = int(rt.get("sold_qty") or 0)
        except Exception as e:
            warnings.append(f"sold_qty_tickets_failed:{type(e).__name__}")
            sold_qty = 0

        # 2) fallback order_items
        if sold_qty == 0:
            try:
                cols_oi = _table_columns(conn, "order_items")
                if cols_oi:
                    ok_expr, fk_expr = _orders_join_exprs()
                    cur.execute(
                        f"""
                        SELECT COALESCE(SUM(oi.qty), 0) AS sold_qty
                        FROM order_items oi
                        JOIN orders o ON {ok_expr} = {fk_expr}
                        WHERE {where_orders}
                          AND o.event_slug = %s
                          AND o.status ILIKE 'PAID'
                        """,
                        (*args_scope_orders, event_slug),
                    )
                    rr2 = cur.fetchone() or {}
                    sold_qty = int(float(rr2.get("sold_qty") or 0))
            except Exception as e:
                warnings.append(f"sold_qty_order_items_failed:{type(e).__name__}")
                sold_qty = 0

        # ---- Revenue by item (mantengo tu lógica) ----
        revenue_by_item = []

        # 1) prefer order_items breakdown
        try:
            cols_oi = _table_columns(conn, "order_items")
            if cols_oi:
                ok_expr, fk_expr = _orders_join_exprs()
                cur.execute(
                    f"""
                    SELECT
                      COALESCE(NULLIF(oi.name, ''), oi.sku, 'item') AS item,
                      COALESCE(oi.kind, '') AS kind,
                      COALESCE(SUM(oi.qty), 0) AS qty,
                      COALESCE(SUM(oi.total_amount), 0) AS amount
                    FROM order_items oi
                    JOIN orders o ON {ok_expr} = {fk_expr}
                    WHERE {where_orders}
                      AND o.event_slug = %s
                      AND o.status ILIKE 'PAID'
                    GROUP BY 1, 2
                    ORDER BY amount DESC NULLS LAST, qty DESC
                    LIMIT 50
                    """,
                    (*args_scope_orders, event_slug),
                )
                for r in cur.fetchall() or []:
                    revenue_by_item.append(
                        {
                            "item": r.get("item"),
                            "kind": r.get("kind"),
                            "qty": float(r.get("qty") or 0),
                            "amount": float(r.get("amount") or 0),
                        }
                    )
        except Exception as e:
            warnings.append(f"revenue_by_item_order_items_failed:{type(e).__name__}")

        # 2) fallback: tickets breakdown
        if not revenue_by_item:
            try:
                where_t, args_scope_t = _scope_where_for_tickets(conn, producer_slug, tenant_id)
                cur.execute(
                    f"""
                    SELECT
                      COALESCE(si.name, 'entrada') AS item,
                      COALESCE(si.kind, 'ticket') AS kind,
                      COUNT(*)::bigint AS qty,
                      COALESCE(SUM(si.price_cents),0)::bigint AS amount_cents
                    FROM tickets t
                    LEFT JOIN sale_items si
                      ON si.id = t.sale_item_id
                     AND si.tenant = %s
                     AND si.event_slug = %s
                    WHERE {where_t}
                      AND t.event_slug = %s
                      AND COALESCE(t.status,'') NOT ILIKE 'revoked'
                    GROUP BY 1, 2
                    ORDER BY amount_cents DESC, qty DESC
                    LIMIT 50
                    """,
                    (producer_slug, event_slug, *args_scope_t, event_slug),
                )
                for r in cur.fetchall() or []:
                    revenue_by_item.append(
                        {
                            "item": r.get("item"),
                            "kind": r.get("kind"),
                            "qty": float(r.get("qty") or 0),
                            "amount": float((r.get("amount_cents") or 0) / 100.0),
                        }
                    )
            except Exception as e:
                warnings.append(f"revenue_by_item_tickets_failed:{type(e).__name__}")

        # ---- Build UI-compatible structures ----
        total_ars = round(revenue_cents / 100.0, 2)
        bar_ars = round(bar_cents / 100.0, 2)
        tickets_count = int(sold_qty or 0)
        avg_ars = round((total_ars / tickets_count), 2) if tickets_count else 0

        # topProducts para el UI (mapea revenue_by_item)
        top_products = []
        for r in (revenue_by_item or [])[:10]:
            top_products.append(
                {
                    "name": r.get("item"),
                    "sales": int(float(r.get("qty") or 0)),
                    "revenue": float(r.get("amount") or 0),
                    "category": "Barra" if (str(r.get("kind") or "").lower() == "bar") else "Entradas",
                }
            )

        # timeSeries (mínimo viable): barras por hora desde orders, tickets por hora desde tickets
        time_series = []
        try:
            # barra por hora
            cur.execute(
                f"""
                SELECT date_trunc('hour', o.created_at) AS h,
                       COALESCE(SUM(COALESCE(o.total_cents, ROUND(o.total_amount * 100)::bigint)),0)::bigint AS cents
                FROM orders o
                WHERE {where_orders}
                  AND o.event_slug = %s
                  AND o.status ILIKE 'PAID'
                  AND (
                        COALESCE(o.source,'')='bar'
                     OR o.bar_slug IS NOT NULL
                     OR COALESCE(o.order_kind,'') ILIKE 'bar'
                     OR COALESCE(o.kind,'') ILIKE 'bar'
                  )
                GROUP BY 1
                ORDER BY 1
                """,
                (*args_scope_orders, event_slug),
            )
            bar_rows = cur.fetchall() or []
            bar_map = {r["h"]: int(r["cents"] or 0) for r in bar_rows if r.get("h")}

            # tickets por hora
            where_t, args_scope_t = _scope_where_for_tickets(conn, producer_slug, tenant_id)
            cur.execute(
                f"""
                SELECT date_trunc('hour', t.created_at) AS h,
                       COUNT(*)::bigint AS qty
                FROM tickets t
                WHERE {where_t}
                  AND t.event_slug=%s
                  AND COALESCE(t.status,'') NOT ILIKE 'revoked'
                GROUP BY 1
                ORDER BY 1
                """,
                (*args_scope_t, event_slug),
            )
            t_rows = cur.fetchall() or []
            t_map = {r["h"]: int(r["qty"] or 0) for r in t_rows if r.get("h")}

            hours = sorted(set(list(bar_map.keys()) + list(t_map.keys())))
            for h in hours[-24:]:  # último 1 día de horas (ajustable)
                time_series.append(
                    {
                        "hour": f"{h.hour:02d}:00",
                        "bar": round((bar_map.get(h, 0) / 100.0), 2),
                        "tickets": int(t_map.get(h, 0)),
                    }
                )
        except Exception as e:
            warnings.append(f"time_series_failed:{type(e).__name__}")

        return {
            "ok": True,
            "warnings": warnings,
            "tenant_id": tenant_id,
            "producer": producer_slug,
            "event": ev,
            "items": items,

            # ✅ UI expects these
            "kpis": {
                "total": total_ars,
                "bar": bar_ars,
                "tickets": tickets_count,
                "avg": avg_ars,

                # mantengo lo viejo (compat)
                "sold": tickets_count,
                "orders_paid": orders_paid,
                "revenue_cents": revenue_cents,
                "revenue_ars": total_ars,
            },

            "topProducts": top_products,
            "timeSeries": time_series,

            # mantengo lo viejo (compat)
            "revenue_by_item": revenue_by_item,
        }

@router.post("/events")
def api_producer_event_create(request: Request, payload: EventCreateIn, user: dict = Depends(_require_auth)):
    """Crea un evento para tenant+producer actuales.

    Importante: inserta solo columnas existentes en la tabla `events`
    (evita romper si el schema todavía no tiene description/lat/lng/etc.).
    """
    tenant_id = _tenant_from_request(request)
    producer = (user or {}).get("producer")
    if not producer:
        raise HTTPException(status_code=401, detail="unauthorized")
    # Keep session in sync (useful for UI routing), but never trust it for auth.
    request.session["producer"] = producer
    tenant = producer
    now_s = _now_epoch_s()

    if not getattr(payload, 'accept_terms', False):
        raise HTTPException(status_code=400, detail='terms_required')


    # slug base (simple y estable)
    base = re.sub(r"[^a-z0-9\s-]+", "", (payload.title or "").strip().lower())
    base = re.sub(r"\s+", "-", base).strip("-") or f"event-{now_s}"

    with get_conn() as conn:
        cols = _table_columns(conn, "events")
        col_types = _table_column_types(conn, "events")

        # generar slug único dentro de tenant+producer
        slug = base
        i = 2
        while True:
            cur = conn.execute(
                """SELECT 1 FROM events WHERE slug = %s LIMIT 1""",
                (slug,),
            )
            if not cur.fetchone():
                break
            slug = f"{base}-{i}"
            i += 1

        data = {
            "tenant_id": tenant_id,
            "tenant": tenant,
            "producer": producer,
            "slug": slug,
            "title": payload.title,
            "date_text": payload.date_text,
            "city": payload.city,
            "venue": payload.venue,
            "hero_bg": payload.hero_bg,
            # opcionales (se insertan solo si existen columnas)
            "description": payload.description,
            "flyer_url": payload.flyer_url,
            "address": payload.address,
            "lat": payload.lat,
            "lng": payload.lng,
            "active": True,
            "created_at": _smart_now_for_column(col_types.get("created_at","")),
            "updated_at": _smart_now_for_column(col_types.get("updated_at","")),
        }
        # si created_at/updated_at no son compatibles, no los mandamos (deja default DB)
        data = {k: v for k, v in data.items() if v is not None}

        ins_cols = [k for k in data.keys() if k in cols]
        ins_vals = [data[k] for k in ins_cols]

        if "active" in cols:
            # compat: algunas tablas usan bool, otras int
            # psycopg adapta True/False ok para ambos
            pass

        sql = f"""INSERT INTO events ({", ".join(ins_cols)}) VALUES ({", ".join(["%s"] * len(ins_cols))}) RETURNING slug"""
        row = conn.execute(sql, tuple(ins_vals)).fetchone()
        conn.commit()

    return {"ok": True, "slug": _row_get(row, key="slug", idx=0, default=slug) if row else slug}

def _event_update_impl(request: Request, slug: str, payload: EventUpdateIn, producer: str):
    """Implementación compartida (PUT y legacy POST).

    Actualiza solo columnas existentes en `events` (evita errores si faltan campos nuevos).
    """
    tenant_id = _tenant_from_request(request)
    tenant = producer
    now_s = _now_epoch_s()

    if not getattr(payload, 'accept_terms', False):
        raise HTTPException(status_code=400, detail='terms_required')


    slug = (slug or "").strip()
    if not slug:
        raise HTTPException(status_code=400, detail="slug_required")

    set_parts: List[str] = []
    params: List[Any] = []

    with get_conn() as conn:
        cols = _table_columns(conn, "events")
        col_types = _table_column_types(conn, "events")

        def add(field: str, value: Any):
            if value is None:
                return
            if field not in cols:
                return
            set_parts.append(f"{field} = %s")
            params.append(value)

        add("title", payload.title)
        add("date_text", payload.date_text)
        add("city", payload.city)
        add("venue", payload.venue)
        add("hero_bg", payload.hero_bg)

        # opcionales (solo si existen columnas)
        add("description", payload.description)
        add("flyer_url", payload.flyer_url)
        add("address", payload.address)
        add("lat", payload.lat)
        add("lng", payload.lng)

        if not set_parts:
            return {"ok": True, "updated": False}

        if "updated_at" in cols:
            set_parts.append("updated_at = %s")
            params.append(_smart_now_for_column(col_types.get("updated_at","")))

        params.extend([tenant_id, producer, slug])

        cur = conn.execute(
            f"""
            UPDATE events
               SET {", ".join(set_parts)}
             WHERE tenant_id = %s AND tenant = %s AND slug = %s
         RETURNING slug
            """,
            tuple(params),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="event_not_found")
        conn.commit()

    # si tu SELECT trae slug como columna "slug"
        return {"ok": True, "updated": True, "slug": row.get("slug")}


def api_producer_event_update(slug: str, request: Request, payload: EventUpdateIn, user: dict = Depends(_require_auth)):
    """Update REST: /events/{slug}"""
    producer = (user or {}).get("producer")
    if not producer:
        raise HTTPException(status_code=401, detail="not_authenticated")
    request.session["producer"] = producer
    return _event_update_impl(request, slug=slug, payload=payload, producer=producer)


@router.post("/events/update")
def api_producer_event_update_legacy(request: Request, payload: EventUpdateIn, user: dict = Depends(_require_auth)):
    """Compat legacy: /events/update (usa payload.slug)."""
    producer = (user or {}).get("producer")
    if not producer:
        raise HTTPException(status_code=401, detail="not_authenticated")
    request.session["producer"] = producer
    return _event_update_impl(request, slug=payload.slug, payload=payload, producer=producer)



# --- Toggle event active/inactive (pausar / publicar) ---
class EventToggleIn(BaseModel):
    tenant_id: str = "default"
    event_slug: str
    is_active: bool = True

@router.post("/events/toggle")
def api_producer_event_toggle(request: Request, payload: EventToggleIn):
    tenant_id = (payload.tenant_id or "default").strip() or "default"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE events SET is_active=%s WHERE tenant_id=%s AND slug=%s",
                (payload.is_active, tenant_id, payload.event_slug),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="event_not_found")
    return {"ok": True}



    
    # SOLUCIÓN AL ERROR DE LOGS:
    # PostgreSQL no acepta 0/1 para campos BOOLEAN. Necesita True/False de Python.
    active = bool(payload.active) if payload.active is not None else True 
    now_v = datetime.now()

    with get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE events
               SET active = %s, updated_at = %s
             WHERE tenant_id = %s AND tenant = %s AND slug = %s
            RETURNING slug
            """,
            (active, now_v, tenant, producer, slug),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="event_not_found")
        conn.commit()

    return {"ok": True, "active": active}

# -------------------------------------------------------------------
# Sale items (ticket/consumición/etc)
# -------------------------------------------------------------------
@router.get("/sale-items")
def api_list_sale_items(request: Request, event: str = "", user: dict = Depends(_require_auth)):
    """Compat: /api/producer/sale-items?event_slug=... or ?event=...  (solo owner)"""
    tenant_id = _tenant_from_request(request)

    producer = (user or {}).get("producer")
    if not producer:
        raise HTTPException(status_code=401, detail="Unauthorized")
    request.session["producer"] = producer

    event_slug = (event or "").strip()
    if not event_slug:
        return []

    with get_conn() as conn:
        # validar que el evento sea del producer
        ok = conn.execute(
            "SELECT 1 FROM events WHERE tenant_id=%s AND slug=%s AND tenant=%s LIMIT 1",
            (tenant_id, event_slug, producer),
        ).fetchone()
        if not ok:
            raise HTTPException(status_code=403, detail="forbidden_event")

        rows = conn.execute(
            """
            SELECT id, name, kind, price_cents, stock_total, COALESCE(stock_sold,0) AS stock_sold,
                   start_date, end_date, active, sort_order, created_at, updated_at
            FROM sale_items
            WHERE tenant = %s AND event_slug = %s
            ORDER BY sort_order ASC, id ASC
            """,
            (producer, event_slug),
        ).fetchall()

    items = [
        {
            "id": r["id"],
            "name": r["name"],
            "kind": r["kind"],
            "price_cents": int(r.get("price_cents") or 0),
            "price": int(r.get("price_cents") or 0),
            "stock_total": int(r.get("stock_total") or 0),
            "stock_sold": int(r.get("stock_sold") or 0),
            "start_date": r.get("start_date"),
            "end_date": r.get("end_date"),
            "active": bool(r.get("active", True)),
            "sort_order": int(r.get("sort_order") or 0),
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
        }
        for r in rows
    ]
    return items


@router.get("/sale-items/{event_slug}")
def api_list_sale_items_by_slug(request: Request, event_slug: str, user: dict = Depends(_require_auth)):
    # para cuando lo llamen por path
    return api_list_sale_items(request, event=event_slug, user=user)



@router.post("/sale-items")
def api_sale_item_create_alias(request: Request, payload: Dict[str, Any], user: dict = Depends(_require_auth)):
    """Alias REST: algunos builds POSTean /sale-items en lugar de /sale-items/create"""
    try:
        data = SaleItemUpsertIn(**(payload or {}))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid_payload: {e}")
    return api_sale_item_create(request, data, user=user)

@router.post("/sale-items/create")
def api_sale_item_create(request: Request, payload: SaleItemUpsertIn, user: dict = Depends(_require_auth)):
    tenant_id = _tenant_from_request(request)
    producer = (user or {}).get("producer")
    if not producer:
        raise HTTPException(status_code=401, detail="Unauthorized")
    request.session["producer"] = producer

    now_s = _now_epoch_s()

    event_slug = payload.event_slug.strip()
    name = payload.name.strip()
    kind = payload.kind.strip()

    # Fechas default (si no pasan nada)
    sd = payload.start_date or str(date.today())
    ed = payload.end_date or str(date.today())

    with get_conn() as conn:
        # validar que el evento sea del producer
        ok = conn.execute(
            "SELECT 1 FROM events WHERE tenant_id=%s AND slug=%s AND tenant=%s LIMIT 1",
            (tenant_id, event_slug, producer),
        ).fetchone()
        if not ok:
            raise HTTPException(status_code=403, detail="forbidden_event")

        # Insert simple (si querés "upsert por nombre", lo hacemos después)
        cur = conn.execute(
            """
            INSERT INTO sale_items (
                tenant, event_slug, name, kind,
                price_cents, stock_total, active, sort_order,
                start_date, end_date,
                created_at, updated_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id, name, kind, price_cents, stock_total, COALESCE(stock_sold,0) AS stock_sold,
                      start_date, end_date, active, sort_order, created_at, updated_at
            """,
            (
                producer,
                event_slug,
                name,
                kind,
                int(payload.price_cents or 0),
                int(payload.stock_total or 0),
                bool(payload.active) if payload.active is not None else True,
                int(payload.sort_order or 0),
                sd,
                ed,
                now_s,
                now_s,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        raise HTTPException(status_code=500, detail="sale_item_insert_failed")

    return {
        "ok": True,
        "sale_item": {
            "id": row["id"],
            "name": row["name"],
            "kind": row["kind"],
            "price_cents": int(row.get("price_cents") or 0),
            "price": int(row.get("price_cents") or 0),
            "stock_total": int(row.get("stock_total") or 0),
            "stock_sold": int(row.get("stock_sold") or 0),
            "start_date": row.get("start_date"),
            "end_date": row.get("end_date"),
            "active": bool(row.get("active", True)),
            "sort_order": int(row.get("sort_order") or 0),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        },
    }
@router.put("/events/{slug}")
def api_producer_event_update(request: Request, slug: str, payload: EventUpdateIn, user: dict = Depends(_require_auth)):
    """Update REST: /events/{slug} (solo owner)"""
    producer = (user or {}).get("producer")
    if not producer:
        raise HTTPException(status_code=401, detail="Unauthorized")
    request.session["producer"] = producer
    return _event_update_impl(request, slug=slug, payload=payload, producer=producer)

@router.post("/sale-items/toggle")
def api_sale_item_toggle(request: Request, payload: SaleItemToggleIn, user: dict = Depends(_require_auth)):
    producer = (user or {}).get("producer")
    if not producer:
        raise HTTPException(status_code=401, detail="Unauthorized")

    with get_conn() as conn:
        col_types = _table_column_types(conn, "sale_items")
        now_v = _smart_now_for_column(col_types.get("updated_at", ""))
        cur = conn.execute(
            """
            UPDATE sale_items
               SET active = %s, updated_at = %s
             WHERE id = %s AND tenant = %s
         RETURNING id
            """,
            (int(payload.active), now_v, int(payload.id), producer),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="sale_item_not_found")
        conn.commit()

    return {"ok": True}


# -------------------------------------------------------------------
# Sellers (event_sellers table)
# -------------------------------------------------------------------
@router.get("/sellers")
def api_list_sellers(request: Request, event: str = ""):
    tenant = _tenant_from_request(request)
    event_slug = (event or "").strip()
    if not event_slug:
        return []

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, tenant, event_slug, code, name, active, created_at, updated_at
            FROM event_sellers
            WHERE tenant = %s AND event_slug = %s
            ORDER BY created_at DESC, id DESC
            """,
            (tenant, event_slug),
        ).fetchall()

    items = [
        {
            "id": r["id"],
            "tenant": r["tenant"],
            "event_slug": r["event_slug"],
            "code": r["code"],
            "name": r["name"],
            "active": bool(r.get("active", True)),
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
        }
        for r in rows
    ]
    return items


@router.post("/sellers/create")
def api_seller_create(request: Request, payload: SellerUpsertIn):
    tenant = _tenant_from_request(request)
    now_s = _now_epoch_s()

    if not getattr(payload, 'accept_terms', False):
        raise HTTPException(status_code=400, detail='terms_required')


    event_slug = payload.event_slug.strip()
    code = payload.code.strip()
    name = payload.name.strip()
    active = bool(payload.active) if payload.active is not None else True

    if not event_slug or not code or not name:
        raise HTTPException(status_code=400, detail="event_slug, code y name son requeridos")

    with get_conn() as conn:
        # upsert por UNIQUE (tenant,event_slug,code)
        cur = conn.execute(
            """
            INSERT INTO event_sellers (tenant, event_slug, code, name, active, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (tenant, event_slug, code)
            DO UPDATE SET name = EXCLUDED.name, active = EXCLUDED.active, updated_at = EXCLUDED.updated_at
            RETURNING id, tenant, event_slug, code, name, active, created_at, updated_at
            """,
            (tenant, event_slug, code, name, active, now_s, now_s),
        )
        row = cur.fetchone()
        conn.commit()

    return {"ok": True, "seller": dict(row)}


@router.post("/sellers/toggle")
def api_seller_toggle(request: Request, payload: SellerToggleIn):
    tenant = _tenant_from_request(request)

    with get_conn() as conn:
        col_types = _table_column_types(conn, "event_sellers")
        now_v = _smart_now_for_column(col_types.get("updated_at", ""))
        cur = conn.execute(
            """
            UPDATE event_sellers
               SET active = %s, updated_at = %s
             WHERE id = %s AND tenant = %s
         RETURNING id
            """,
            (int(payload.active), now_v, int(payload.id), producer),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="seller_not_found")
        conn.commit()

    return {"ok": True}


# -------------------------------------------------------------------
# Nota rápida (psql):
# En psql no podés tirar "WHERE tenant = %s" o "$1" así nomás.
# Eso es placeholder de drivers. En psql usás valores literales:
#   WHERE tenant='demo' AND producer='ger';
# o preparás una query con PREPARE/EXECUTE.
# -------------------------------------------------------------------
def _row_get(row, key=None, idx=None, default=None):
    """Safe getter for DB rows that may be tuple/list, dict, or mapping (psycopg rows)."""
    if row is None:
        return default
    if key is not None:
        try:
            return row[key]  # type: ignore[index]
        except Exception:
            pass
    if idx is not None:
        try:
            return row[idx]  # type: ignore[index]
        except Exception:
            pass
    # fallback: first value
    try:
        it = iter(row.values())  # type: ignore[attr-defined]
        return next(it)
    except Exception:
        try:
            return next(iter(row))
        except Exception:
            return default



# ---------------------------
# Aliases (front/back compat)
# ---------------------------
# En el front a veces aparecen como "vendors" y "sales-items".
# En el backend original eran /sellers y /sale-items.

@router.get("/vendors")
def api_list_vendors(request: Request):
    return api_list_sellers(request)

@router.post("/vendors")
def api_create_vendor(payload: dict, request: Request):
    return api_create_seller(payload, request)

@router.put("/vendors/{seller_id}")
def api_update_vendor(seller_id: int, payload: dict, request: Request):
    return api_update_seller(seller_id, payload, request)

@router.delete("/vendors/{seller_id}")
def api_delete_vendor(seller_id: int, request: Request):
    return api_delete_seller(seller_id, request)

@router.get("/sales-items")
def api_list_sales_items(request: Request, event: str = ""):
    return api_list_sale_items(request, event)

@router.post("/sales-items")
def api_create_sales_item(payload: dict, request: Request):
    return api_create_sale_item(payload, request)

@router.put("/sales-items/{item_id}")
def api_update_sales_item(item_id: int, payload: dict, request: Request):
    return api_update_sale_item(item_id, payload, request)

@router.delete("/sales-items/{item_id}")
def api_delete_sales_item(item_id: int, request: Request):
    return api_delete_sale_item(item_id, request)
