from __future__ import annotations

import os
import uuid
import shutil
from datetime import date, datetime, timezone
from typing import Any, Optional, List

from fastapi import APIRouter, Request, HTTPException, Depends, Query, UploadFile, File, Form
from pydantic import BaseModel, Field, root_validator
from starlette.responses import JSONResponse

from app.db import get_conn

from psycopg.rows import dict_row
from psycopg import errors as pg_errors
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



def _invalidate_table_columns_cache(table: str, schema: str = "public") -> None:
    key = f"{schema}.{table}"
    if hasattr(_table_columns, "_cache") and key in _table_columns._cache:
        del _table_columns._cache[key]


def _ensure_sale_items_schema(conn) -> None:
    """No-op: no tocamos schema en producción desde la app.

    La compatibilidad se resuelve adaptando queries/models al schema real.
    """
    return



def _ensure_sellers_schema(conn) -> None:
    """No-op: no creamos tablas desde la app.

    Sellers para Entradas se resuelve sobre `event_sellers` (si existe) o devolviendo lista vacía.
    """
    return


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

def _can_edit_event(tenant_id: str, event_slug: str, producer: str) -> bool:
    """True si el producer es dueño del evento.

    Compatibilidad: en versiones anteriores, la "propiedad" del evento se guardó
    en `events.tenant`; en otras, en `events.producer`. Por eso aceptamos ambas.
    """
    if not tenant_id or not event_slug or not producer:
        return False
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM events
            WHERE tenant_id = %s
              AND slug = %s
              AND (
                    tenant = %s
                 OR producer = %s
              )
            LIMIT 1
            """,
            (tenant_id, event_slug, producer, producer),
        ).fetchone()
        return bool(row)


from fastapi import UploadFile, File
import pathlib

def _uploads_dir() -> str:
    d = os.getenv("UPLOAD_DIR", "/var/data/uploads")
    os.makedirs(d, exist_ok=True)
    return d


def _ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path

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

    return {"ok": True, "url": f"/uploads/{fname}"}

@router.post("/events/{slug}/flyer")
async def api_event_upload_flyer(
    slug: str,
    request: Request,
    tenant_id: str = Query("default"),
    file: UploadFile = File(...),
):
    """Sube flyer/cover para un evento específico y actualiza events.flyer_url.

    Guarda en el Disk de Render (por defecto /var/data/uploads) y sirve por /uploads/...
    """
    user = _require_auth(request)
    producer_id = _norm_id(str(user.get("producer") or ""))

    if not _can_edit_event(tenant_id, slug, producer_id):
        raise HTTPException(status_code=403, detail="forbidden")

    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="file_required")

    # Guardamos sin leer todo a memoria
    ext = pathlib.Path(file.filename).suffix.lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        raise HTTPException(status_code=400, detail="invalid_file_type")

    safe_slug = _norm_id(slug)
    target_dir = _ensure_dir(os.path.join(_uploads_dir(), "events", tenant_id, safe_slug))
    fname = f"flyer-{uuid.uuid4().hex}{ext}"
    fpath = os.path.join(target_dir, fname)

    with open(fpath, "wb") as out:
        shutil.copyfileobj(file.file, out)

    public_url = f"/uploads/events/{tenant_id}/{safe_slug}/{fname}"

    # Persistimos URL en DB
    with get_conn() as conn:
        conn.execute(
            "UPDATE events SET flyer_url = %s WHERE tenant = %s AND slug = %s",
            (public_url, tenant_id, safe_slug),
        )
        conn.commit()

    return {"ok": True, "url": public_url}




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


def _ensure_events_columns(conn) -> None:
    """Ensure the 'events' table contains columns used by the UI.
    Works for both SQLite and Postgres-ish backends (best-effort).
    """
    desired = {
        "flyer_url": "TEXT",
        "hero_bg": "TEXT",
        "description": "TEXT",
        "address": "TEXT",
        "city": "TEXT",
        "venue": "TEXT",
        "lat": "REAL",
        "lng": "REAL",
        "updated_at": "TEXT",
    }
    try:
        cols = set(_table_columns(conn, "events"))
    except Exception:
        # If we can't introspect, don't block writes.
        return

    missing = [c for c in desired.keys() if c not in cols]
    if not missing:
        return

    for c in missing:
        coltype = desired[c]
        # Try Postgres syntax first, then SQLite.
        try:
            conn.execute(f'ALTER TABLE events ADD COLUMN IF NOT EXISTS {c} {coltype}')
        except Exception:
            try:
                conn.execute(f'ALTER TABLE events ADD COLUMN {c} {coltype}')
            except Exception:
                # If still failing, keep going; we'll just not persist that field.
                continue

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

def _pg_columns(conn, table_name: str) -> set[str]:
    """Devuelve columnas reales de una tabla (schema public)."""
    rows = conn.execute(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = %s
        """,
        (table_name,),
    ).fetchall()
    cols = set()
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        cols.add(d.get("column_name"))
    return cols



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
    tenant_id: Optional[str] = 'default'
    event_slug: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    kind: str = Field(default="ticket", min_length=1)

    # Compat: frontend puede mandar price (ARS) y stock
    price: Optional[float] = None
    stock: Optional[int] = None
    # legacy compat (algunos front viejos mandaban capacity en vez de stock)
    capacity: Optional[int] = None

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
    tenant_id: Optional[str] = 'default'
    event_slug: str = Field(..., min_length=1)
    code: str = Field(..., min_length=1)  # código corto (ej: "vendedor1")
    # compat: algunos UI mandan pin explícito
    pin: Optional[str] = None
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
        # Compatibilidad: algunos eventos tienen el dueño en `tenant`, otros en `producer`.
        rows = conn.execute(
            """
            SELECT slug, title, date_text, city, venue, active, hero_bg
            FROM events
            WHERE tenant_id = %s
              AND (tenant = %s OR producer = %s)
            ORDER BY created_at DESC
            LIMIT 200
            """,
            (tenant_id, producer, producer),
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
async def api_producer_event_create(
    request: Request,
    user: dict = Depends(_require_auth),
    title: str = Form(...),
    date_text: Optional[str] = Form(None),
    city: Optional[str] = Form(None),
    venue: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    accept_terms: bool = Form(False),
    address: Optional[str] = Form(None),
    lat: Optional[float] = Form(None),
    lng: Optional[float] = Form(None),
    hero_bg: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
):
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

    if not accept_terms:
        raise HTTPException(status_code=400, detail='terms_required')

    # slug base (simple y estable)
    base = re.sub(r"[^a-z0-9\s-]+", "", (title or "").strip().lower())
    base = re.sub(r"\s+", "-", base).strip("-") or f"event-{now_s}"

    flyer_public_url = None
    if file and file.filename:
        # Guardamos sin leer todo a memoria
        ext = pathlib.Path(file.filename).suffix.lower()
        if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
            raise HTTPException(status_code=400, detail="invalid_file_type")

        safe_slug_base = _norm_id(base)
        target_dir = _ensure_dir(os.path.join(_uploads_dir(), "events", tenant_id, safe_slug_base))
        fname = f"flyer-{uuid.uuid4().hex}{ext}"
        fpath = os.path.join(target_dir, fname)

        with open(fpath, "wb") as out:
            shutil.copyfileobj(file.file, out)

        flyer_public_url = f"/uploads/events/{tenant_id}/{safe_slug_base}/{fname}"


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
            "title": title,
            "date_text": date_text,
            "city": city,
            "venue": venue,
            "hero_bg": hero_bg,
            # opcionales (se insertan solo si existen columnas)
            "description": description,
            "flyer_url": flyer_public_url,
            "address": address,
            "lat": lat,
            "lng": lng,
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

        # WHERE: compatibilidad con ownership guardado en tenant o en producer
        params.extend([tenant_id, producer, producer, slug])

        cur = conn.execute(
            f"""
            UPDATE events
               SET {", ".join(set_parts)}
             WHERE tenant_id = %s AND (tenant = %s OR producer = %s) AND slug = %s
         RETURNING slug
            """,
            tuple(params),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="event_not_found")
        conn.commit()
    return {"ok": True, "updated": True, "slug": (row.get("slug") if isinstance(row, dict) else (dict(row).get("slug") if row is not None else slug))}


@router.put("/events/{slug}")
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
def api_producer_event_toggle(request: Request, payload: EventToggleIn, user: dict = Depends(_require_auth)):
    tenant_id = (payload.tenant_id or 'default').strip() or 'default'
    producer = user.get("producer")
    if not _can_edit_event(tenant_id, payload.event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden_event")

    with get_conn() as conn:
        row = conn.execute(
            """
            UPDATE events
            SET is_active = %s
            WHERE tenant_id = %s AND (tenant = %s OR producer = %s) AND slug = %s
            RETURNING slug
            """,
            (bool(payload.is_active), tenant_id, producer, producer, payload.event_slug),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="event_not_found")
        conn.commit()
    return {"ok": True}


    
    # SOLUCIÓN AL ERROR DE LOGS:
    # PostgreSQL no acepta 0/1 para campos BOOLEAN. Necesita True/False de Python.
    active = bool(payload.active) 
    now_v = datetime.now()

    with get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE events
               SET active = %s, updated_at = %s
             WHERE tenant_id = %s AND (tenant = %s OR producer = %s) AND slug = %s
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
def api_sale_items(
    request: Request,
    tenant_id: str = Query("default"),
    event_slug: str = Query(...),
    user: dict = Depends(_require_auth),
):
    """
    Lista sale_items del evento (solo si el productor es dueño del evento).

    Schema real (public.sale_items):
      - tenant (text)  -> producer
      - event_slug (text)
      - stock_total / stock_sold (int)

    Para no romper front legacy, devolvemos además:
      - stock: disponible (stock_total - stock_sold)
    """
    producer = user.get("producer")
    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden_event")

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                si.id,
                si.tenant,
                si.event_slug,
                si.name,
                COALESCE(si.kind, 'ticket') AS kind,
                COALESCE(si.price_cents, 0) AS price_cents,
                COALESCE(si.stock_total, 0) AS stock_total,
                COALESCE(si.stock_sold, 0) AS stock_sold,
                COALESCE(si.start_date, '') AS start_date,
                COALESCE(si.end_date, '') AS end_date,
                COALESCE(si.active, TRUE) AS active,
                COALESCE(si.display_order, 0) AS display_order,
                si.created_at,
                si.updated_at
            FROM sale_items si
            JOIN events e
              ON e.slug = si.event_slug
             AND (e.tenant = si.tenant OR e.producer = si.tenant)
            WHERE e.tenant_id = %s
              AND e.slug = %s
              AND (e.tenant = %s OR e.producer = %s)
            ORDER BY COALESCE(si.display_order, 0) ASC, si.id ASC
            """,
            (tenant_id, event_slug, producer, producer),
        ).fetchall()

    items = []
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        stock_total = int(d.get("stock_total") or 0)
        stock_sold = int(d.get("stock_sold") or 0)
        stock_avail = max(stock_total - stock_sold, 0)

        items.append(
            {
                "id": d.get("id"),
                "tenant": d.get("tenant"),
                "event_slug": d.get("event_slug"),
                "name": d.get("name"),
                "kind": d.get("kind"),
                "price_cents": int(d.get("price_cents") or 0),
                "stock_total": stock_total,
                "stock_sold": stock_sold,
                "stock_available": stock_avail,
                # legacy
                "stock": stock_avail,
                "start_date": d.get("start_date") or None,
                "end_date": d.get("end_date") or None,
                "active": bool(d.get("active", True)),
                "display_order": int(d.get("display_order") or 0),
                "created_at": d.get("created_at"),
                "updated_at": d.get("updated_at"),
            }
        )

    return {"ok": True, "items": items}


@router.post("/sale-items/create")
def api_sale_item_create(
    request: Request,
    payload: SaleItemUpsertIn,
    tenant_id: str = Query("default"),
    user: dict = Depends(_require_auth),
):
    """
    Crea (o actualiza) un sale_item para un evento del productor logueado.

    Nota: Nos alineamos al schema real:
      - tenant (productor)
      - stock_total / stock_sold
      - NO existe tenant_id en sale_items, por eso validamos contra events y luego escribimos tenant=producer.
    """
    tenant_id = ((getattr(payload, "tenant_id", None) or tenant_id or "default")).strip() or "default"
    producer = user.get("producer")
    event_slug = (payload.event_slug or "").strip()
    if not event_slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")

    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden_event")

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="missing_name")

    kind = (payload.kind or "ticket").strip() or "ticket"
    price_cents = int(payload.price_cents or 0)

    # stock_total: prioridad a stock_total; si no, stock/capacity legacy
    stock_total = payload.stock_total
    if (stock_total is None) or (int(stock_total) == 0 and (payload.stock or payload.capacity)):
        stock_total = payload.stock if payload.stock is not None else payload.capacity
    stock_total = int(stock_total or 0)
    if stock_total < 0:
        stock_total = 0

    start_date = (payload.start_date or None)
    end_date = (payload.end_date or None)
    active = bool(payload.active) if payload.active is not None else True
    display_order = int(payload.sort_order or 0)

    now_s = _now_epoch_s()

    with get_conn() as conn:
        # Upsert por unique constraint real: (tenant, event_slug, kind, name)
        row = conn.execute(
            """
            INSERT INTO sale_items (
                tenant, event_slug, name, kind,
                price_cents, stock_total, stock_sold,
                start_date, end_date,
                active, display_order,
                created_at, updated_at,
                item_name, item_type
            )
            VALUES (%s,%s,%s,%s,%s,%s,0,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (tenant, event_slug, kind, name)
            DO UPDATE SET
                price_cents   = EXCLUDED.price_cents,
                stock_total   = EXCLUDED.stock_total,
                start_date    = EXCLUDED.start_date,
                end_date      = EXCLUDED.end_date,
                active        = EXCLUDED.active,
                display_order = EXCLUDED.display_order,
                updated_at    = EXCLUDED.updated_at,
                item_name     = EXCLUDED.item_name,
                item_type     = EXCLUDED.item_type
            RETURNING
                id, tenant, event_slug, name, kind, price_cents,
                stock_total, stock_sold, start_date, end_date,
                active, display_order, created_at, updated_at
            """,
            (
                producer,
                event_slug,
                name,
                kind,
                price_cents,
                stock_total,
                start_date,
                end_date,
                active,
                display_order,
                now_s,
                now_s,
                name,
                kind,
            ),
        ).fetchone()
        conn.commit()

    d = dict(row) if not isinstance(row, dict) else row
    st = int(d.get("stock_total") or 0)
    ss = int(d.get("stock_sold") or 0)
    avail = max(st - ss, 0)

    return {
        "ok": True,
        "item": {
            **d,
            "stock_available": avail,
            "stock": avail,  # legacy
        },
    }


@router.put("/sale-items/{sale_item_id}")
def api_sale_item_update(
    request: Request,
    sale_item_id: int,
    payload: SaleItemUpsertIn,
    user: dict = Depends(_require_auth),
):
    """
    Actualiza un sale_item (solo si pertenece al evento del productor).

    Alineado a schema real: stock_total / stock_sold.
    """
    tenant_id = (payload.tenant_id or "default").strip() or "default"
    producer = user.get("producer")
    event_slug = (payload.event_slug or "").strip()
    if not event_slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")

    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden_event")

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="missing_name")

    kind = (payload.kind or "ticket").strip() or "ticket"
    price_cents = int(payload.price_cents or 0)

    stock_total = payload.stock_total
    if (stock_total is None) or (int(stock_total) == 0 and (payload.stock or payload.capacity)):
        stock_total = payload.stock if payload.stock is not None else payload.capacity
    stock_total = int(stock_total or 0)
    if stock_total < 0:
        stock_total = 0

    start_date = (payload.start_date or None)
    end_date = (payload.end_date or None)
    active = bool(payload.active) if payload.active is not None else True
    display_order = int(payload.sort_order or 0)
    now_s = _now_epoch_s()

    with get_conn() as conn:
        row = conn.execute(
            """
            UPDATE sale_items
               SET name         = %s,
                   kind         = %s,
                   price_cents   = %s,
                   stock_total   = %s,
                   start_date    = %s,
                   end_date      = %s,
                   active        = %s,
                   display_order = %s,
                   updated_at    = %s,
                   item_name     = %s,
                   item_type     = %s
             WHERE id = %s
               AND tenant = %s
               AND event_slug = %s
            RETURNING
                id, tenant, event_slug, name, kind, price_cents,
                stock_total, stock_sold, start_date, end_date,
                active, display_order, created_at, updated_at
            """,
            (
                name,
                kind,
                price_cents,
                stock_total,
                start_date,
                end_date,
                active,
                display_order,
                now_s,
                name,
                kind,
                sale_item_id,
                producer,
                event_slug,
            ),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="sale_item_not_found")

        conn.commit()

    d = dict(row) if not isinstance(row, dict) else row
    st = int(d.get("stock_total") or 0)
    ss = int(d.get("stock_sold") or 0)
    avail = max(st - ss, 0)
    d["stock_available"] = avail
    d["stock"] = avail  # legacy

    return {"ok": True, "item": d}


@router.delete("/sale-items/{sale_item_id}")
def api_sale_item_delete(
    request: Request,
    sale_item_id: int,
    tenant_id: str = Query("default"),
    event_slug: str = Query(...),
    user: dict = Depends(_require_auth),
):
    producer = user.get("producer")
    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden_event")

    with get_conn() as conn:
        deleted = conn.execute(
            """
            DELETE FROM sale_items
             WHERE tenant = %s
               AND event_slug = %s
               AND id = %s
            """,
            (producer, event_slug, sale_item_id),
        ).rowcount
        conn.commit()

    if not deleted:
        raise HTTPException(status_code=404, detail="sale_item_not_found")
    return {"ok": True, "deleted": True}


@router.get("/sellers")
def api_list_sellers(
    request: Request,
    tenant_id: str = Query("default"),
    event_slug: str = Query(...),
    user: dict = Depends(_require_auth),
):
    """
    Lista sellers del evento.

    En la DB real NO existe tabla `sellers`; usamos `event_sellers` si está disponible.
    Si no existe, devolvemos lista vacía (sin 500) para no romper el panel.
    """
    producer = user.get("producer")
    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden_event")

    with get_conn() as conn:
        try:
            cols = _pg_columns(conn, "event_sellers")
        except Exception:
            cols = set()

        if not cols:
            return {"ok": True, "sellers": []}

        # IMPORTANTE: al hacer JOIN con events, columnas como `name` pueden ser ambiguas.
        # Por eso calificamos con alias `es.` y exponemos alias de salida.
        sel = ["es.id AS id", "es.event_slug AS event_slug"]
        if "name" in cols:
            sel.append("es.name AS name")
        if "pin" in cols:
            sel.append("es.pin AS pin")
        elif "code" in cols:
            sel.append("es.code AS pin")
        if "created_at" in cols:
            sel.append("es.created_at AS created_at")
        if "updated_at" in cols:
            sel.append("es.updated_at AS updated_at")

        # scoping: tenant/event_slug + validación por events. Preferimos tenant si existe.
        where = ["es.event_slug = %s"]
        params = [event_slug]

        if "tenant" in cols:
            where.append("es.tenant = %s")
            params.append(producer)

        query = f"""
            SELECT {", ".join(sel)}
              FROM event_sellers es
              JOIN events e
                ON e.slug = es.event_slug
             WHERE e.tenant_id = %s
               AND e.slug = %s
               AND (e.tenant = %s OR e.producer = %s)
               AND {" AND ".join(where)}
             ORDER BY es.id ASC
        """

        try:
            rows = conn.execute(query, (tenant_id, event_slug, producer, producer, *params)).fetchall()
        except pg_errors.UndefinedTable:
            return {"ok": True, "sellers": []}

    sellers = [dict(r) if not isinstance(r, dict) else r for r in rows]
    return {"ok": True, "sellers": sellers}


@router.post("/sellers/create")
def api_seller_create(
    request: Request,
    payload: SellerUpsertIn,
    user: dict = Depends(_require_auth),
):
    """
    Crea un seller para un evento (tabla real: event_sellers).
    """
    tenant_id = (payload.tenant_id or "default").strip() or "default"
    producer = user.get("producer")
    event_slug = (payload.event_slug or "").strip()
    if not event_slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")

    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden_event")

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="missing_name")

    pin = (payload.pin or payload.code or "").strip()
    if not pin:
        raise HTTPException(status_code=400, detail="missing_pin")

    now_s = _now_epoch_s()

    with get_conn() as conn:
        try:
            cols = _pg_columns(conn, "event_sellers")
        except Exception:
            cols = set()

        if not cols:
            raise HTTPException(status_code=501, detail="event_sellers_table_missing")

        fields = []
        values = []
        params = []

        # tenant / event_slug son clave
        if "tenant" in cols:
            fields.append("tenant")
            values.append("%s")
            params.append(producer)

        fields.append("event_slug")
        values.append("%s")
        params.append(event_slug)

        if "name" in cols:
            fields.append("name")
            values.append("%s")
            params.append(name)

        if "pin" in cols:
            fields.append("pin")
            values.append("%s")
            params.append(pin)
        elif "code" in cols:
            fields.append("code")
            values.append("%s")
            params.append(pin)

        if "created_at" in cols:
            fields.append("created_at")
            values.append("%s")
            params.append(now_s)

        q = f"INSERT INTO event_sellers ({', '.join(fields)}) VALUES ({', '.join(values)}) RETURNING id"
        try:
            row = conn.execute(q, tuple(params)).fetchone()
            conn.commit()
        except pg_errors.UndefinedTable:
            raise HTTPException(status_code=501, detail="event_sellers_table_missing")

        new_id = (dict(row).get("id") if row else None) if not isinstance(row, dict) else row.get("id")

    return {"ok": True, "seller": {"id": new_id, "event_slug": event_slug, "name": name, "pin": pin}}


@router.put("/sellers/{seller_id}")
def api_seller_update(
    request: Request,
    seller_id: int,
    payload: SellerUpsertIn,
    user: dict = Depends(_require_auth),
):
    tenant_id = (payload.tenant_id or "default").strip() or "default"
    producer = user.get("producer")
    event_slug = (payload.event_slug or "").strip()
    if not event_slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")

    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden_event")

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="missing_name")
    pin = (payload.pin or payload.code or "").strip()
    if not pin:
        raise HTTPException(status_code=400, detail="missing_pin")

    now_s = _now_epoch_s()

    with get_conn() as conn:
        try:
            cols = _pg_columns(conn, "event_sellers")
        except Exception:
            cols = set()

        if not cols:
            raise HTTPException(status_code=501, detail="event_sellers_table_missing")

        sets = []
        params = []

        if "name" in cols:
            sets.append("name = %s")
            params.append(name)

        if "pin" in cols:
            sets.append("pin = %s")
            params.append(pin)
        elif "code" in cols:
            sets.append("code = %s")
            params.append(pin)

        if "updated_at" in cols:
            sets.append("updated_at = %s")
            params.append(now_s)

        if not sets:
            raise HTTPException(status_code=400, detail="no_updatable_columns")

        where = ["id = %s", "event_slug = %s"]
        params_where = [seller_id, event_slug]

        if "tenant" in cols:
            where.append("tenant = %s")
            params_where.append(producer)

        q = f"UPDATE event_sellers SET {', '.join(sets)} WHERE {' AND '.join(where)} RETURNING id, event_slug"
        try:
            row = conn.execute(q, tuple(params + params_where)).fetchone()
            conn.commit()
        except pg_errors.UndefinedTable:
            raise HTTPException(status_code=501, detail="event_sellers_table_missing")

    if not row:
        raise HTTPException(status_code=404, detail="seller_not_found")

    return {"ok": True, "seller": {"id": seller_id, "event_slug": event_slug, "name": name, "pin": pin}}


@router.delete("/sellers/{seller_id}")
def api_seller_delete(
    request: Request,
    seller_id: int,
    tenant_id: str = Query("default"),
    event_slug: str = Query(...),
    user: dict = Depends(_require_auth),
):
    producer = user.get("producer")
    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden_event")

    with get_conn() as conn:
        try:
            cols = _pg_columns(conn, "event_sellers")
        except Exception:
            cols = set()

        if not cols:
            raise HTTPException(status_code=501, detail="event_sellers_table_missing")

        where = ["id = %s", "event_slug = %s"]
        params = [seller_id, event_slug]
        if "tenant" in cols:
            where.append("tenant = %s")
            params.append(producer)

        q = f"DELETE FROM event_sellers WHERE {' AND '.join(where)}"
        try:
            deleted = conn.execute(q, tuple(params)).rowcount
            conn.commit()
        except pg_errors.UndefinedTable:
            raise HTTPException(status_code=501, detail="event_sellers_table_missing")

    if not deleted:
        raise HTTPException(status_code=404, detail="seller_not_found")
    return {"ok": True, "deleted": True}


# Aliases (compat)
@router.get("/vendors")
def api_list_vendors(
    request: Request,
    tenant_id: str = Query("default"),
    event_slug: str = Query(...),
    user: dict = Depends(_require_auth),
):
    return api_list_sellers(request, tenant_id=tenant_id, event_slug=event_slug, user=user)


@router.post("/vendors/create")
def api_vendor_create(
    request: Request,
    payload: SellerUpsertIn,
    user: dict = Depends(_require_auth),
):
    return api_seller_create(request, payload=payload, user=user)


@router.put("/vendors/{seller_id}")
def api_vendor_update(
    request: Request,
    seller_id: int,
    payload: SellerUpsertIn,
    user: dict = Depends(_require_auth),
):
    return api_seller_update(request, seller_id=seller_id, payload=payload, user=user)


@router.delete("/vendors/{seller_id}")
def api_vendor_delete(
    request: Request,
    seller_id: int,
    tenant_id: str = Query("default"),
    event_slug: str = Query(...),
    user: dict = Depends(_require_auth),
):
    return api_seller_delete(request, seller_id=seller_id, tenant_id=tenant_id, event_slug=event_slug, user=user)

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
