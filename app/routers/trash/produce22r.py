from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional, List

from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel, Field, root_validator
from starlette.responses import JSONResponse

from app.db import get_conn
from contextlib import contextmanager


@contextmanager
def get_db():
    """Compat helper: some endpoints expect get_db()."""
    conn = get_conn()
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


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
    """Resolve tenant_id from (1) header, (2) query params, (3) session.

    The frontend sometimes sends tenant_id (or tenant) as query params.
    We accept both for compatibility.
    """
    # Header primero: permite que el frontend fuerce el tenant activo sin pelearse con session.
    ht = request.headers.get("x-tenant")
    if isinstance(ht, str) and ht.strip():
        return _norm_id(ht, default="default")

    # Query params (lo que usa el frontend hoy)
    qp = getattr(request, "query_params", None)
    if qp is not None:
        q = qp.get("tenant_id") or qp.get("tenant")
        if isinstance(q, str) and q.strip():
            return _norm_id(q, default="default")

    # Session fallback
    st = None
    if hasattr(request, "session"):
        st = request.session.get("tenant_id") or request.session.get("tenant")

    return _norm_id(str(st), default="default")

def _producer_from_request(request: Request) -> str:
    """Resuelve el producer efectivo.

    Regla: header primero (x-producer), luego session.

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


def _get_event_row(db, tenant_id: str, slug: str):
    """Fetch event row by tenant_id + slug.

    Returns a dict or None.
    """
    db.execute(
        "SELECT * FROM events WHERE tenant_id = %s AND slug = %s",
        (tenant_id, slug),
    )
    row = db.fetchone()
    return dict(row) if row else None


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
def api_producer_events(request: Request):
    """Devuelve SOLO eventos del producer actual."""
    tenant_id = _tenant_from_request(request)
    producer = _producer_from_request(request)
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




@router.get("/dashboard")
def api_producer_dashboard(
    request: Request,
    tenant_id: str = "default",
    event_slug: str = "",
    user=Depends(_require_auth),
):
    """
    Producer dashboard for a given event.

    Notes on terminology:
    - tenant_id: platform tenant / environment (usually "default")
    - events.tenant: producer slug (ex: "atico")
    """
    tenant_id = _norm_id(tenant_id, default=_tenant_from_request(request))
    event_slug = (event_slug or "").strip().lower()

    if not event_slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")

    with get_conn() as conn:
        cur = conn.cursor(row_factory=dict_row)

        # ---- Load event ----
        cur.execute(
            """
            SELECT slug, title, date_text, city, venue, flyer_url, active, tenant
            FROM events
            WHERE tenant_id = %s AND slug = %s
            """,
            (tenant_id, event_slug),
        )
        ev = cur.fetchone()
        if not ev:
            raise HTTPException(status_code=404, detail="event_not_found")

        producer_slug = (ev.get("tenant") or "").strip()

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

        # ---- KPIs (orders + items) ----
        orders_paid = 0
        revenue_cents = 0
        sold_qty = 0
        try:
            cur.execute(
                """
                SELECT
                  COUNT(*) FILTER (WHERE status ILIKE 'PAID') AS orders_paid,
                  COALESCE(
                    SUM(COALESCE(total_cents, ROUND(total_amount * 100)::bigint))
                    FILTER (WHERE status ILIKE 'PAID'),
                    0
                  ) AS revenue_cents
                FROM orders
                WHERE tenant_id = %s AND event_slug = %s
                """,
                (tenant_id, event_slug),
            )
            rr = cur.fetchone() or {}
            orders_paid = int(rr.get("orders_paid") or 0)
            revenue_cents = int(rr.get("revenue_cents") or 0)

            cur.execute(
                """
                SELECT COALESCE(SUM(oi.qty), 0) AS sold_qty
                FROM order_items oi
                JOIN orders o ON o.id::text = oi.order_id
                WHERE o.tenant_id = %s
                  AND o.event_slug = %s
                  AND o.status ILIKE 'PAID'
                """,
                (tenant_id, event_slug),
            )
            rr2 = cur.fetchone() or {}
            sold_qty = int(float(rr2.get("sold_qty") or 0))
        except Exception:
            # Dashboard should not crash for partial metrics issues
            pass

        # ---- Revenue by item (tickets + bar items together) ----
        revenue_by_item = []
        try:
            cur.execute(
                """
                SELECT
                  COALESCE(NULLIF(oi.name, ''), oi.sku, 'item') AS item,
                  COALESCE(oi.kind, '') AS kind,
                  COALESCE(SUM(oi.qty), 0) AS qty,
                  COALESCE(SUM(oi.total_amount), 0) AS amount
                FROM order_items oi
                JOIN orders o ON o.id::text = oi.order_id
                WHERE o.tenant_id = %s
                  AND o.event_slug = %s
                  AND o.status ILIKE 'PAID'
                GROUP BY 1, 2
                ORDER BY amount DESC NULLS LAST, qty DESC
                LIMIT 50
                """,
                (tenant_id, event_slug),
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
        except Exception:
            pass

        return {
            "ok": True,
            "tenant_id": tenant_id,
            "producer": producer_slug,
            "event": ev,
            "items": items,
            "kpis": {
                "sold": sold_qty,
                "orders_paid": orders_paid,
                "revenue_cents": revenue_cents,
                "revenue_ars": round(revenue_cents / 100.0, 2),
            },
            "revenue_by_item": revenue_by_item,
        }
@router.post("/events")
def api_producer_event_create(request: Request, payload: EventCreateIn):
    """Crea un evento para tenant+producer actuales.

    Importante: inserta solo columnas existentes en la tabla `events`
    (evita romper si el schema todavía no tiene description/lat/lng/etc.).
    """
    tenant_id = _tenant_from_request(request)
    producer = _producer_from_request(request)
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

def _event_update_impl(request: Request, slug: str, payload: EventUpdateIn):
    """Actualiza un evento.

    Importante:
    - Versiones anteriores filtraban por `tenant = producer` y además exigían aceptar términos en cada update.
    - Para evitar el error "event_not_found" en ediciones (cuando el producer en sesión cambia),
      buscamos el evento por (tenant_id + slug) y actualizamos ese registro.
    """

    tenant_id = _tenant_from_request(request)
    now_s = _now_epoch_s()

    slug = (slug or "").strip()
    if not slug:
        raise HTTPException(status_code=400, detail="slug_required")

    set_parts: List[str] = []
    params: List[Any] = []

    with get_conn() as conn:
        cols = _table_columns(conn, "events")
        col_types = _table_column_types(conn, "events")

        # Confirmar existencia
        cur_ev = conn.execute(
            "SELECT slug FROM events WHERE tenant_id = %s AND slug = %s",
            (tenant_id, slug),
        )
        if not cur_ev.fetchone():
            raise HTTPException(status_code=404, detail="event_not_found")

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

        # opcionales
        add("description", payload.description)
        add("flyer_url", payload.flyer_url)
        add("address", payload.address)
        add("lat", payload.lat)
        add("lng", payload.lng)

        if not set_parts:
            return {"ok": True, "updated": False, "slug": slug}

        if "updated_at" in cols:
            set_parts.append("updated_at = %s")
            params.append(_smart_now_for_column(col_types.get("updated_at", "")))

        params.extend([tenant_id, slug])

        cur = conn.execute(
            f"""
            UPDATE events
               SET {", ".join(set_parts)}
             WHERE tenant_id = %s AND slug = %s
         RETURNING slug
            """,
            tuple(params),
        )
        row = cur.fetchone()
        conn.commit()
    if not row:
        raise HTTPException(status_code=404, detail="event_not_found")

    # Return the fresh event payload (frontend expects the event fields)
    with get_db() as db:
        db.execute("SELECT * FROM events WHERE tenant_id = %s AND slug = %s", (tenant_id, slug))
        ev = db.fetchone()
        return dict(ev) if ev else {"ok": True, "slug": slug}



def api_producer_event_update(slug: str, request: Request, payload: EventUpdateIn):
    """Update REST: /events/{slug}"""
    return _event_update_impl(request, slug=slug, payload=payload)


@router.post("/events/update")
def api_producer_event_update_legacy(request: Request, payload: EventUpdateIn):
    """Compat legacy: /events/update (usa payload.slug)."""
    return _event_update_impl(request, slug=payload.slug, payload=payload)



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

# -------------------------------------------------------------------
# Sale items (ticket/consumición/etc)
# -------------------------------------------------------------------
@router.get("/sale-items")
async def api_list_sale_items(
    request: Request,
    tenant_id: str = "default",
    event_slug: str = "",
    event: str = "",
):
    """List sale items for an event.

    The UI uses: /api/producer/sale-items?tenant_id=...&event_slug=...
    Older callers might send event=...
    """
    tenant_id = _tenant_from_request(request) or _norm_id(tenant_id, default="default")
    # tenant here means the event owner/producer
    slug = (event_slug or event or "").strip()
    if not slug:
        return []

    with get_db() as db:
        ev = _get_event_row(db, tenant_id, slug)
        tenant = (ev.get("tenant") if ev else None) or _producer_from_request(request)

    with get_db() as db:
        col_types = _table_column_types(db, "sale_items")
        where = ["tenant = %s", "event_slug = %s"]
        params = [tenant, slug]
        if "tenant_id" in col_types:
            where.insert(0, "tenant_id = %s")
            params.insert(0, tenant_id)

        q = f"""
            SELECT id, event_slug, name, price_cents, COALESCE(stock_total, 0) AS stock_total,
                   COALESCE(stock_sold, 0) AS stock_sold, COALESCE(active, TRUE) AS active
            FROM sale_items
            WHERE {' AND '.join(where)}
            ORDER BY id ASC
        """
        cur = db.execute(q, params)
        rows = cur.fetchall() or []
        return [
            {
                "id": r[0],
                "event_slug": r[1],
                "name": r[2],
                "price_cents": int(r[3]),
                "price_ars": round(int(r[3]) / 100.0, 2),
                "stock_total": int(r[4]) if r[4] is not None else 0,
                "stock_sold": int(r[5]) if r[5] is not None else 0,
                "active": bool(r[6]),
            }
            for r in rows
        ]


@router.post("/sale-items/create")
async def api_sale_item_create(request: Request, payload: SaleItemUpsertIn) -> Any:
    tenant_id = _tenant_from_request(request)

    # Validate
    event_slug = _norm_id(payload.event_slug)
    if not event_slug:
        raise HTTPException(status_code=400, detail="event_slug_required")

    # Attach this item to the event owner (producer) to stay consistent across sessions.
    with get_db() as db:
        ev = _get_event_row(db, tenant_id, event_slug)
        tenant = (ev.get("tenant") if ev else None) or _producer_from_request(request)

        col_types = _table_column_types(db, "sale_items")
        has_tid = "tenant_id" in col_types

        # Keep this consistent with list() filtering.
        cols = ["tenant", "event_slug", "name", "price_cents", "active", "is_ticket", "stock_total", "stock_left"]
        vals = [
            tenant,
            event_slug,
            payload.name,
            int(payload.price_cents),
            True,
            bool(payload.is_ticket),
            int(payload.stock_total),
            int(payload.stock_total),
        ]
        if has_tid:
            cols.insert(0, "tenant_id")
            vals.insert(0, tenant_id)

        placeholders = ", ".join(["%s"] * len(cols))
        sql = f"""
            INSERT INTO sale_items ({', '.join(cols)})
            VALUES ({placeholders})
            RETURNING id
        """
        row = db.fetchone(sql, tuple(vals))
        if not row:
            raise HTTPException(status_code=500, detail="insert_failed")

    return {"ok": True, "id": int(row[0])}

@router.put("/events/{slug}")
def api_producer_event_update(request: Request, slug: str, payload: EventUpdateIn):
    """Update REST: /events/{slug}"""
    return _event_update_impl(request, slug=slug, payload=payload)

@router.post("/sale-items/toggle")
async def api_sale_item_toggle(request: Request, payload: SaleItemToggleIn) -> Any:
    tenant_id = _tenant_from_request(request)

    with get_db() as conn:
        col_types = _table_column_types(conn, "sale_items")
        has_tid = "tenant_id" in col_types

        now_v = datetime.utcnow()
        if has_tid:
            cur = conn.execute(
                """
                UPDATE sale_items
                   SET active = %s, updated_at = %s
                 WHERE id = %s AND tenant_id = %s
             RETURNING id
                """,
                (int(payload.active), now_v, int(payload.id), tenant_id),
            )
        else:
            cur = conn.execute(
                """
                UPDATE sale_items
                   SET active = %s, updated_at = %s
                 WHERE id = %s
             RETURNING id
                """,
                (int(payload.active), now_v, int(payload.id)),
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
async def api_list_sellers(
    request: Request,
    tenant_id: str = "default",
    event_slug: str = "",
    event: str = "",  # compat
) -> Any:
    tenant_id = _tenant_from_request(request) or _norm_id(tenant_id, default="default")

    slug = (event_slug or event or "").strip()
    if not slug:
        return []

    with get_db() as db:
        ev = _get_event_row(db, tenant_id, slug)
        if not ev:
            return []
        tenant = ev.get("tenant") or _producer_from_request(request)

        col_types = _table_column_types(db, "event_sellers")
        has_tid = "tenant_id" in col_types
        where = "tenant = %s AND event_slug = %s"
        params = [tenant, slug]
        if has_tid:
            where = "tenant_id = %s AND " + where
            params = [tenant_id] + params

        db.execute(
            f"""
            SELECT id, code, name, active
            FROM event_sellers
            WHERE {where}
            ORDER BY name ASC
            """,
            tuple(params),
        )
        rows = db.fetchall() or []
        return [dict(r) for r in rows]

@router.post("/sellers/create")
async def api_seller_create(request: Request, payload: SellerCreateIn):
    tenant_id = _tenant_from_request(request)

    # Encontramos el evento por slug (sin importar el producer actual)
    with get_db() as db:
        db.execute(
            "SELECT tenant, accept_terms FROM events WHERE tenant_id = %s AND slug = %s",
            (tenant_id, _norm_id(payload.event_slug)),
        )
        ev = db.fetchone()

        if not ev:
            raise HTTPException(status_code=404, detail="event_not_found")

        event_producer, accept_terms = ev

        # Gate de términos:
        # - Si el payload trae accept_terms=True => ok.
        # - Si NO lo trae, permitimos sólo si el evento ya tenía accept_terms=True.
        if payload.accept_terms is not True and accept_terms is not True:
            raise HTTPException(status_code=400, detail="terms_required")

        # Insert seller
        col_types = _table_column_types(db, "event_sellers")
        has_tid = "tenant_id" in col_types

        cols = ["tenant", "event_slug", "code", "name", "active", "created_at"]
        vals = [event_producer, _norm_id(payload.event_slug), payload.code.strip(), payload.name.strip(), True, _now_utc()]
        if has_tid:
            cols.insert(0, "tenant_id")
            vals.insert(0, tenant_id)

        cols_sql = ", ".join(cols)
        ph = ", ".join(["%s"] * len(vals))
        db.execute(
            f"INSERT INTO event_sellers ({cols_sql}) VALUES ({ph})",
            tuple(vals),
        )

    return {"ok": True}

@router.post("/sellers/toggle")
def api_seller_toggle(request: Request, payload: SellerToggleIn):
    tenant_id = _tenant_from_request(request)

    with get_conn() as conn:
        col_types = _table_column_types(conn, "event_sellers")
        now_s = _now_epoch_s()
        has_tid = "tenant_id" in col_types

        if has_tid:
            cur = conn.execute(
                """
                UPDATE event_sellers
                   SET active = %s, updated_at = %s
                 WHERE id = %s AND tenant_id = %s
             RETURNING id
                """,
                (int(payload.active), now_s, int(payload.id), tenant_id),
            )
        else:
            cur = conn.execute(
                """
                UPDATE event_sellers
                   SET active = %s, updated_at = %s
                 WHERE id = %s
             RETURNING id
                """,
                (int(payload.active), now_s, int(payload.id)),
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
