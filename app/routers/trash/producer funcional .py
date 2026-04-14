from __future__ import annotations

import os
import re
import unicodedata
import uuid
import pathlib
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request, HTTPException, Depends, UploadFile, File
from pydantic import BaseModel, Field, root_validator
from starlette.responses import JSONResponse

from psycopg.rows import dict_row

from app.db import get_conn

router = APIRouter(tags=["producer"])


# -------------------------------------------------------------------
# Normalización
# -------------------------------------------------------------------
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
# Auth / identidad
# -------------------------------------------------------------------
def _require_auth(request: Request) -> dict:
    """Auth dependency for producer routes.

    Accepts either:
      - a logged-in session (request.session['user'])
      - or a debug header 'x-producer' (useful for local/dev testing)
    """
    # Debug/local shortcut
    hdr = (request.headers.get("x-producer") or "").strip()
    if hdr:
        return {"producer": _norm_id(hdr), "auth": "header"}

    user = None
    if hasattr(request, "session"):
        user = request.session.get("user") or request.session.get("profile")

    if not user:
        raise HTTPException(status_code=401, detail="not_authenticated")

    # Ensure producer slug
    producer = user.get("producer") if isinstance(user, dict) else None
    if not producer and isinstance(user, dict):
        email = user.get("email") or user.get("preferred_username")
        if isinstance(email, str) and "@" in email:
            producer = email.split("@", 1)[0]
    if not producer and isinstance(user, dict):
        producer = user.get("sub") or user.get("id")
    if producer and isinstance(user, dict):
        user["producer"] = _norm_id(str(producer))

    return user if isinstance(user, dict) else {"user": user}


def _tenant_id_from_request(request: Request) -> str:
    """Platform tenant_id. Hoy siempre default."""
    ht = (request.headers.get("x-tenant-id") or "").strip()
    if ht:
        return _norm_id(ht, default="default")
    t = (request.session.get("tenant_id") if hasattr(request, "session") else None) or "default"
    return _norm_id(str(t), default="default")


def _producer_from_request(request: Request) -> str:
    """Resuelve el producer efectivo.
    Regla: header x-producer primero, luego session (y normaliza).
    """
    hp = (request.headers.get("x-producer") or "").strip()
    if hp:
        return _norm_id(hp, default="ger")

    # session user
    if hasattr(request, "session"):
        u = request.session.get("user") or request.session.get("profile") or {}
        if isinstance(u, dict):
            if isinstance(u.get("producer"), str) and u["producer"].strip():
                return _norm_id(u["producer"])
            email = u.get("email") or u.get("preferred_username")
            if isinstance(email, str) and "@" in email:
                return _norm_id(email.split("@", 1)[0])
            sub = u.get("sub") or u.get("id")
            if isinstance(sub, str) and sub.strip():
                return _norm_id(sub)

    return "ger"


# -------------------------------------------------------------------
# DB utils
# -------------------------------------------------------------------
def _table_columns(conn, table: str, schema: str = "public") -> set[str]:
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
            v = r.get("column_name") or next(iter(r.values()), None)
        else:
            v = r[0] if r else None
        if v:
            cols.add(str(v))
    cache[key] = cols
    return cols


def _table_column_types(conn, table: str, schema: str = "public") -> dict[str, str]:
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
            name = r.get("column_name")
            dtype = r.get("data_type")
        else:
            name = r[0] if len(r) > 0 else None
            dtype = r[1] if len(r) > 1 else None
        if name:
            out[str(name)] = str(dtype or "")
    cache[key] = out
    return out


def _now_epoch_s() -> int:
    return int(datetime.utcnow().timestamp())


def _smart_now_for_column(col_type: str):
    t = (col_type or "").lower()
    if "timestamp" in t or "date" in t or "time" in t:
        return datetime.now(timezone.utc)
    if "int" in t or "numeric" in t or "double" in t or "real" in t or "decimal" in t:
        return _now_epoch_s()
    return None


def _row_get(row, key=None, idx=None, default=None):
    if row is None:
        return default
    if key is not None:
        try:
            return row[key]
        except Exception:
            pass
    if idx is not None:
        try:
            return row[idx]
        except Exception:
            pass
    try:
        it = iter(row.values())
        return next(it)
    except Exception:
        try:
            return next(iter(row))
        except Exception:
            return default


# -------------------------------------------------------------------
# Uploads
# -------------------------------------------------------------------
def _uploads_dir() -> str:
    d = os.getenv("UPLOAD_DIR", "static/uploads")
    os.makedirs(d, exist_ok=True)
    return d


@router.post("/upload/flyer")
async def upload_flyer(
    request: Request,
    file: UploadFile = File(...),
    user=Depends(_require_auth),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="file_required")

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
# Schemas
# -------------------------------------------------------------------
class EventCreateIn(BaseModel):
    title: str = Field(..., min_length=1)
    date_text: Optional[str] = None
    city: Optional[str] = None
    venue: Optional[str] = None
    description: Optional[str] = None
    accept_terms: bool = False
    flyer_url: Optional[str] = None
    hero_bg: Optional[str] = None
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class EventUpdateIn(BaseModel):
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


class SaleItemUpsertIn(BaseModel):
    event_slug: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    kind: str = Field(default="ticket", min_length=1)

    price: Optional[float] = None
    stock: Optional[int] = None

    price_cents: int = Field(default=0, ge=0)
    stock_total: int = Field(default=0, ge=0)

    start_date: Optional[str] = None
    end_date: Optional[str] = None

    active: bool = Field(default=True)
    sort_order: int = Field(default=0, ge=0)

    @root_validator(pre=True)
    def _compat_price_stock(cls, values):
        if (
            ("price_cents" not in values)
            or (values.get("price_cents") is None)
            or (
                values.get("price_cents") == 0
                and values.get("price") not in (None, 0, "0", 0.0)
            )
        ):
            p = values.get("price")
            if p is not None:
                try:
                    values["price_cents"] = int(round(float(p) * 100))
                except Exception:
                    pass

        if (
            ("stock_total" not in values)
            or (values.get("stock_total") is None)
            or (
                values.get("stock_total") == 0
                and values.get("stock") not in (None, 0, "0")
            )
        ):
            s = values.get("stock")
            if s is not None:
                try:
                    values["stock_total"] = int(s)
                except Exception:
                    pass
        return values


class SaleItemToggleIn(BaseModel):
    id: int
    active: int = Field(..., ge=0, le=1)


class SellerUpsertIn(BaseModel):
    event_slug: str = Field(..., min_length=1)
    code: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    active: bool = Field(default=True)


class SellerToggleIn(BaseModel):
    id: int
    active: int = Field(..., ge=0, le=1)


# -------------------------------------------------------------------
# Identity
# -------------------------------------------------------------------
@router.get("/me")
def api_me(request: Request, user=Depends(_require_auth)):
    tenant_id = _tenant_id_from_request(request)
    producer = _producer_from_request(request)
    return JSONResponse({"ok": True, "tenant_id": tenant_id, "tenant": producer, "producer": producer, "user": user})


# -------------------------------------------------------------------
# Events
# -------------------------------------------------------------------
@router.get("/events")
def api_producer_events(request: Request, user=Depends(_require_auth)):
    tenant_id = _tenant_id_from_request(request)
    producer = _producer_from_request(request)

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

    return JSONResponse(
        content=[
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
    )


@router.post("/events")
def api_producer_event_create(request: Request, payload: EventCreateIn, user=Depends(_require_auth)):
    tenant_id = _tenant_id_from_request(request)
    producer = _producer_from_request(request)

    if not getattr(payload, "accept_terms", False):
        raise HTTPException(status_code=400, detail="terms_required")

    base = re.sub(r"[^a-z0-9\s-]+", "", (payload.title or "").strip().lower())
    base = re.sub(r"\s+", "-", base).strip("-") or f"event-{_now_epoch_s()}"

    with get_conn() as conn:
        cols = _table_columns(conn, "events")
        col_types = _table_column_types(conn, "events")

        slug = base
        i = 2
        while True:
            cur = conn.execute("""SELECT 1 FROM events WHERE tenant_id=%s AND slug=%s LIMIT 1""", (tenant_id, slug))
            if not cur.fetchone():
                break
            slug = f"{base}-{i}"
            i += 1

        data = {
            "tenant_id": tenant_id,
            "tenant": producer,
            "producer": producer,
            "slug": slug,
            "title": payload.title,
            "date_text": payload.date_text,
            "city": payload.city,
            "venue": payload.venue,
            "hero_bg": payload.hero_bg,
            "description": payload.description,
            "flyer_url": payload.flyer_url,
            "address": payload.address,
            "lat": payload.lat,
            "lng": payload.lng,
            "active": True,
            "created_at": _smart_now_for_column(col_types.get("created_at", "")),
            "updated_at": _smart_now_for_column(col_types.get("updated_at", "")),
        }
        data = {k: v for k, v in data.items() if v is not None and k in cols}

        ins_cols = list(data.keys())
        ins_vals = [data[k] for k in ins_cols]
        sql = f"""INSERT INTO events ({", ".join(ins_cols)}) VALUES ({", ".join(["%s"] * len(ins_cols))}) RETURNING slug"""
        row = conn.execute(sql, tuple(ins_vals)).fetchone()
        conn.commit()

    return {"ok": True, "slug": _row_get(row, key="slug", idx=0, default=slug) if row else slug}


def _event_update_impl(request: Request, slug: str, payload: EventUpdateIn):
    tenant_id = _tenant_id_from_request(request)
    producer = _producer_from_request(request)

    # Si el front manda accept_terms en update, no lo exigimos (solo en create).
    slug = (slug or "").strip()
    if not slug:
        raise HTTPException(status_code=400, detail="slug_required")

    with get_conn() as conn:
        cols = _table_columns(conn, "events")
        col_types = _table_column_types(conn, "events")
        cur = conn.cursor(row_factory=dict_row)

        # 1) existe?
        cur.execute("SELECT tenant FROM events WHERE tenant_id=%s AND slug=%s LIMIT 1", (tenant_id, slug))
        ev = cur.fetchone()
        if not ev:
            raise HTTPException(status_code=404, detail="event_not_found")

        # 2) ownership
        ev_tenant = (ev.get("tenant") or "").strip()
        if _norm_id(ev_tenant, default="") != _norm_id(producer, default=""):
            raise HTTPException(status_code=403, detail="forbidden_not_owner")

        set_parts: List[str] = []
        params: List[Any] = []

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

        params.extend([tenant_id, producer, slug])

        cur.execute(
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
            # raro, pero por las dudas
            raise HTTPException(status_code=404, detail="event_not_found")
        conn.commit()

    return {"ok": True, "updated": True, "slug": row.get("slug")}


@router.put("/events/{slug}")
def api_producer_event_update(request: Request, slug: str, payload: EventUpdateIn, user=Depends(_require_auth)):
    return _event_update_impl(request, slug=slug, payload=payload)


@router.post("/events/update")
def api_producer_event_update_legacy(request: Request, payload: EventUpdateIn, user=Depends(_require_auth)):
    return _event_update_impl(request, slug=payload.slug, payload=payload)


class EventToggleIn(BaseModel):
    event_slug: str
    is_active: bool = True


@router.post("/events/toggle")
def api_producer_event_toggle(request: Request, payload: EventToggleIn, user=Depends(_require_auth)):
    tenant_id = _tenant_id_from_request(request)
    producer = _producer_from_request(request)

    slug = (payload.event_slug or "").strip()
    if not slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")

    with get_conn() as conn:
        cols = _table_columns(conn, "events")
        col_types = _table_column_types(conn, "events")
        cur = conn.cursor(row_factory=dict_row)

        cur.execute("SELECT tenant FROM events WHERE tenant_id=%s AND slug=%s LIMIT 1", (tenant_id, slug))
        ev = cur.fetchone()
        if not ev:
            raise HTTPException(status_code=404, detail="event_not_found")
        if _norm_id(ev.get("tenant") or "", default="") != _norm_id(producer, default=""):
            raise HTTPException(status_code=403, detail="forbidden_not_owner")

        if "active" not in cols:
            raise HTTPException(status_code=500, detail="schema_missing_events_active")

        now_v = _smart_now_for_column(col_types.get("updated_at", "")) if "updated_at" in cols else None

        if now_v is not None and "updated_at" in cols:
            cur.execute(
                "UPDATE events SET active=%s, updated_at=%s WHERE tenant_id=%s AND tenant=%s AND slug=%s",
                (bool(payload.is_active), now_v, tenant_id, producer, slug),
            )
        else:
            cur.execute(
                "UPDATE events SET active=%s WHERE tenant_id=%s AND tenant=%s AND slug=%s",
                (bool(payload.is_active), tenant_id, producer, slug),
            )

        conn.commit()

    return {"ok": True, "active": bool(payload.is_active)}


# -------------------------------------------------------------------
# Dashboard (ya estaba bien: toma tenant del evento para items)
# -------------------------------------------------------------------
@router.get("/dashboard")
def api_producer_dashboard(
    request: Request,
    tenant_id: str = "default",
    event_slug: str = "",
    user=Depends(_require_auth),
):
    tenant_id = _norm_id(tenant_id, default=_tenant_id_from_request(request))
    event_slug = (event_slug or "").strip().lower()
    if not event_slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")

    with get_conn() as conn:
        cur = conn.cursor(row_factory=dict_row)

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

        # Ownership: el producer logueado debe ser el dueño
        producer = _producer_from_request(request)
        if _norm_id(producer_slug, default="") != _norm_id(producer, default=""):
            raise HTTPException(status_code=403, detail="forbidden_not_owner")

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

        return {"ok": True, "tenant_id": tenant_id, "producer": producer_slug, "event": ev, "items": items}


# -------------------------------------------------------------------
# Sale items (ticket/consumición/etc) - Producer scope (tenant = producer)
# -------------------------------------------------------------------
@router.get("/sale-items")
def api_list_sale_items(request: Request, event: str = "", user=Depends(_require_auth)):
    producer = _producer_from_request(request)
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
            (producer, event_slug),
        ).fetchall()

    return [
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


@router.get("/sale-items/{event_slug}")
def api_list_sale_items_by_slug(request: Request, event_slug: str, user=Depends(_require_auth)):
    return api_list_sale_items(request, event=event_slug, user=user)


@router.post("/sale-items/create")
def api_sale_item_create(request: Request, payload: SaleItemUpsertIn, user=Depends(_require_auth)):
    producer = _producer_from_request(request)
    now_s = _now_epoch_s()

    event_slug = payload.event_slug.strip()
    name = payload.name.strip()
    kind = payload.kind.strip()

    sd = payload.start_date or str(date.today())
    ed = payload.end_date or str(date.today())

    with get_conn() as conn:
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


@router.post("/sale-items/toggle")
def api_sale_item_toggle(request: Request, payload: SaleItemToggleIn, user=Depends(_require_auth)):
    producer = _producer_from_request(request)

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
# Sellers (event_sellers) - Producer scope (tenant = producer)
# -------------------------------------------------------------------
@router.get("/sellers")
def api_list_sellers(request: Request, event: str = "", user=Depends(_require_auth)):
    producer = _producer_from_request(request)
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
            (producer, event_slug),
        ).fetchall()

    return [
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


@router.post("/sellers/create")
def api_seller_create(request: Request, payload: SellerUpsertIn, user=Depends(_require_auth)):
    producer = _producer_from_request(request)
    now_s = _now_epoch_s()

    event_slug = payload.event_slug.strip()
    code = payload.code.strip()
    name = payload.name.strip()
    active = bool(payload.active)

    if not event_slug or not code or not name:
        raise HTTPException(status_code=400, detail="event_slug, code y name son requeridos")

    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO event_sellers (tenant, event_slug, code, name, active, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (tenant, event_slug, code)
            DO UPDATE SET name = EXCLUDED.name, active = EXCLUDED.active, updated_at = EXCLUDED.updated_at
            RETURNING id, tenant, event_slug, code, name, active, created_at, updated_at
            """,
            (producer, event_slug, code, name, active, now_s, now_s),
        )
        row = cur.fetchone()
        conn.commit()

    return {"ok": True, "seller": dict(row)}


@router.post("/sellers/toggle")
def api_seller_toggle(request: Request, payload: SellerToggleIn, user=Depends(_require_auth)):
    producer = _producer_from_request(request)

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
# Aliases front/back compat (sin romper import)
# -------------------------------------------------------------------
@router.get("/vendors")
def api_list_vendors(request: Request, event: str = "", user=Depends(_require_auth)):
    return api_list_sellers(request, event=event, user=user)


@router.post("/vendors/create")
def api_create_vendor(request: Request, payload: SellerUpsertIn, user=Depends(_require_auth)):
    return api_seller_create(request, payload=payload, user=user)


@router.get("/sales-items")
def api_list_sales_items(request: Request, event: str = "", user=Depends(_require_auth)):
    return api_list_sale_items(request, event=event, user=user)


@router.post("/sales-items/create")
def api_create_sales_item(request: Request, payload: SaleItemUpsertIn, user=Depends(_require_auth)):
    return api_sale_item_create(request, payload=payload, user=user)
