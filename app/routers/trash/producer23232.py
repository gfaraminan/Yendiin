from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional, List

from fastapi import APIRouter, Request, HTTPException
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


router = APIRouter()

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
    _ = _producer_from_request(request)  # dispara 401 si no hay sesión

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



# -------------------------------------------------------------------
# Helpers (tenant/producer). Hasta que haya auth real, usamos defaults.
# -------------------------------------------------------------------
def _tenant_from_request(request: Request) -> str:
    # Header primero: permite que el frontend fuerce el tenant activo sin pelearse con session.
    ht = request.headers.get("x-tenant")
    if isinstance(ht, str) and ht.strip():
        return _norm_id(ht, default="demo")
    t = (request.session.get("tenant") if hasattr(request, "session") else None) or "demo"
    return _norm_id(str(t), default="demo")


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
        if values.get('price_cents') is None:
            p = values.get('price')
            if p is not None:
                try:
                    values['price_cents'] = int(round(float(p) * 100))
                except Exception:
                    pass
        # stock -> stock_total
        if values.get('stock_total') is None:
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
    tenant = _tenant_from_request(request)
    producer = _producer_from_request(request)

    user = None
    if hasattr(request, "session"):
        sp = request.session.get("producer")
        if isinstance(sp, dict):
            user = {
                "id": sp.get("id"),
                "name": sp.get("name"),
                "email": sp.get("email"),
            }

    return JSONResponse({"ok": True, "tenant": tenant, "producer": producer, "user": user})


# -------------------------------------------------------------------
# Events
# -------------------------------------------------------------------
@router.get("/events")
def api_producer_events(request: Request):
    """Devuelve SOLO eventos del producer actual."""
    tenant = _tenant_from_request(request)
    producer = _producer_from_request(request)

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT slug, title, date_text, city, venue, active, hero_bg
            FROM events
            WHERE tenant = %s AND producer = %s
            ORDER BY created_at DESC
            LIMIT 200
            """,
            (tenant, producer),
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
def producer_dashboard(tenant_id: str, event_slug: str):
    """Dashboard productor.

    Fixes:
    - No depende de columnas que no existen (events.id/status, sale_items.tenant_id, order_items.*).
    - Busca evento por slug de forma tolerante (case-insensitive).
    - Agrega sale items reales y métricas desde orders.total_cents/items_json.
    """
    norm_slug = (event_slug or "").strip()
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # 1) Evento (tolerante a mayúsculas/minúsculas)
            cur.execute(
                """
                SELECT slug, COALESCE(title, name, slug) AS title, date_text, city, venue, flyer_url, active, hero_bg, description
                FROM events
                WHERE tenant_id = %s AND (slug = %s OR lower(slug) = lower(%s))
                LIMIT 1
                """,
                (tenant_id, norm_slug, norm_slug),
            )
            ev = cur.fetchone()
            if not ev:
                raise HTTPException(status_code=404, detail="event_not_found")

            real_slug = ev["slug"]

            # 2) Sale items (tabla real: sale_items.tenant + event_slug)
            cur.execute(
                """
                SELECT
                    id,
                    name,
                    kind,
                    price_cents,
                    stock_total,
                    stock_sold,
                    active,
                    sort_order,
                    start_date,
                    end_date,
                    item_name,
                    item_type,
                    display_order
                FROM sale_items
                WHERE tenant = %s AND event_slug = %s
                ORDER BY COALESCE(display_order, sort_order, 0) ASC, id ASC
                """,
                (tenant_id, real_slug),
            )
            items = cur.fetchall() or []

            # 3) Órdenes y métricas (source of truth: orders.total_cents + items_json)
            cur.execute(
                """
                SELECT id, status, order_kind, total_cents, customer_id, auth_provider, auth_subject, items_json
                FROM orders
                WHERE tenant_id = %s AND event_slug = %s
                ORDER BY created_at DESC
                """,
                (tenant_id, real_slug),
            )
            orders_rows = cur.fetchall() or []

    # 4) Métricas y best sellers (en Python: items_json puede variar)
    total_orders = 0
    total_cents = 0
    by_kind = {"ticket": {"orders": 0, "cents": 0}, "bar": {"orders": 0, "cents": 0}, "unknown": {"orders": 0, "cents": 0}}
    customers = set()
    best = {}  # key -> {name, kind, qty, cents}

    for o in orders_rows:
        status = (o.get("status") or "").lower()
        # contamos todo; si querés filtrar solo pagadas, cambiá acá:
        # if status not in ("paid", "ready", "delivered"): continue
        total_orders += 1
        cents = int(o.get("total_cents") or 0)
        total_cents += cents

        okind = (o.get("order_kind") or "").lower() or "unknown"
        if okind not in by_kind:
            okind = "unknown"
        by_kind[okind]["orders"] += 1
        by_kind[okind]["cents"] += cents

        cid = o.get("customer_id") or (f"{o.get('auth_provider','')}:{o.get('auth_subject','')}" if o.get("auth_subject") else None)
        if cid:
            customers.add(cid)

        ij = o.get("items_json")
        if not ij:
            continue
        try:
            # items_json puede ser dict con 'items' o lista directa
            payload = ij
            if isinstance(payload, str):
                payload = json.loads(payload)
            if isinstance(payload, dict):
                arr = payload.get("items") or payload.get("lines") or payload.get("order_items") or []
            elif isinstance(payload, list):
                arr = payload
            else:
                arr = []
            for it in arr:
                if not isinstance(it, dict):
                    continue
                name = it.get("name") or it.get("title") or it.get("item_name") or "item"
                kind = (it.get("kind") or it.get("type") or okind or "unknown")
                qty = int(it.get("qty") or it.get("quantity") or 1)
                line_cents = it.get("total_cents")
                if line_cents is None:
                    # a veces viene price_cents + qty
                    pc = it.get("price_cents") or it.get("unit_price_cents") or 0
                    try:
                        line_cents = int(pc) * qty
                    except Exception:
                        line_cents = 0
                else:
                    try:
                        line_cents = int(line_cents)
                    except Exception:
                        line_cents = 0

                key = f"{kind}::{name}".lower()
                rec = best.get(key) or {"name": name, "kind": kind, "qty": 0, "cents": 0}
                rec["qty"] += qty
                rec["cents"] += line_cents
                best[key] = rec
        except Exception:
            # No rompemos el dashboard por un JSON raro
            pass

    best_list = sorted(best.values(), key=lambda r: (r["qty"], r["cents"]), reverse=True)[:20]

    return {
        "ok": True,
        "event": ev,
        "sale_items": items,
        "metrics": {
            "orders_total": total_orders,
            "total_cents": total_cents,
            "unique_customers": len(customers),
            "by_kind": by_kind,
            "best_sellers": best_list,
        },
    }


@router.post("/events")
def api_producer_event_create(request: Request, payload: EventCreateIn):
    """Crea un evento para tenant+producer actuales.

    Importante: inserta solo columnas existentes en la tabla `events`
    (evita romper si el schema todavía no tiene description/lat/lng/etc.).
    """
    tenant = _tenant_from_request(request)
    producer = _producer_from_request(request)
    now_s = _now_epoch_s()

    if not getattr(payload, 'accept_terms', False):
        raise HTTPException(status_code=400, detail='terms_required')


    # slug base (simple y estable)
    base = re.sub(r"[^a-z0-9\s-]+", "", (payload.title or "").strip().lower())
    base = re.sub(r"\s+", "-", base).strip("-") or f"event-{now_s}"

    with get_conn() as conn:
        cols = _table_columns(conn, "events")
        col_types = _table_column_types(conn, "events")
        col_types = _table_column_types(conn, "events")

        # generar slug único dentro de tenant+producer
        slug = base
        i = 2
        while True:
            cur = conn.execute(
                """SELECT 1 FROM events WHERE tenant = %s AND producer = %s AND slug = %s LIMIT 1""",
                (tenant, producer, slug),
            )
            if not cur.fetchone():
                break
            slug = f"{base}-{i}"
            i += 1

        data = {
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
    """Implementación compartida (PUT y legacy POST).

    Actualiza solo columnas existentes en `events` (evita errores si faltan campos nuevos).
    """
    tenant = _tenant_from_request(request)
    producer = _producer_from_request(request)
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

        params.extend([tenant, producer, slug])

        cur = conn.execute(
            f"""
            UPDATE events
               SET {", ".join(set_parts)}
             WHERE tenant = %s AND producer = %s AND slug = %s
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



    
    # SOLUCIÓN AL ERROR DE LOGS:
    # PostgreSQL no acepta 0/1 para campos BOOLEAN. Necesita True/False de Python.
    active = bool(payload.active) 
    now_v = datetime.now()

    with get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE events
               SET active = %s, updated_at = %s
             WHERE tenant = %s AND producer = %s AND slug = %s
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
def api_list_sale_items(request: Request, event: str = ""):
    """Compat: /api/producer/sale-items?event=slug"""
    tenant = _tenant_from_request(request)
    event_slug = (event or "").strip()
    if not event_slug:
        return []

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, name, kind, price_cents, stock_total, COALESCE(stock_sold,0) AS stock_sold,
                   start_date, end_date, active, sort_order, created_at, updated_at
            FROM sale_items
            WHERE tenant = %s AND event_slug = %s
            ORDER BY sort_order ASC, id ASC
            """,
            (tenant, event_slug),
        ).fetchall()

    items = [
        {
            "id": r["id"],
            "name": r["name"],
            "kind": r["kind"],
            "price_cents": int(r.get("price_cents") or 0),
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
def api_list_sale_items_by_slug(request: Request, event_slug: str):
    # para cuando lo llamen por path
    return api_list_sale_items(request, event=event_slug)


@router.post("/sale-items/create")
def api_sale_item_create(request: Request, payload: SaleItemUpsertIn):
    tenant = _tenant_from_request(request)
    now_s = _now_epoch_s()

    if not getattr(payload, 'accept_terms', False):
        raise HTTPException(status_code=400, detail='terms_required')


    event_slug = payload.event_slug.strip()
    name = payload.name.strip()
    kind = payload.kind.strip()

    # Fechas default (si no pasan nada)
    sd = payload.start_date or str(date.today())
    ed = payload.end_date or str(date.today())

    with get_conn() as conn:
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
                tenant,
                event_slug,
                name,
                kind,
                int(payload.price_cents or 0),
                int(payload.stock_total or 0),
                bool(payload.active),
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
def api_producer_event_update(request: Request, slug: str, payload: EventUpdateIn):
    """Update REST: /events/{slug}"""
    return _event_update_impl(request, slug=slug, payload=payload)

@router.post("/sale-items/toggle")
def api_sale_item_toggle(request: Request, payload: SaleItemToggleIn):
    tenant = _tenant_from_request(request)

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
            (int(payload.active), now_v, int(payload.id), tenant),
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
    active = bool(payload.active)

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
            (int(payload.active), now_v, int(payload.id), tenant),
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