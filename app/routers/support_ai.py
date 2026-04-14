from __future__ import annotations

import os
import json
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import APIRouter, HTTPException, Request

from pydantic import BaseModel, Field
from app.db import get_conn
import re
from app.support_ai.schemas import SupportAIChatRequest, SupportAIChatResponse
from app.support_ai.service import SupportAIService

router = APIRouter(tags=["support-ai"])


class SupportAIStatusResponse(BaseModel):
    enabled: bool
    is_staff: bool
    model: str | None = None
    has_openai_key: bool
    has_vector_store: bool


class SupportAIAdminDashboardResponse(BaseModel):
    tenant_id: str
    event_filter: str | None = None
    active_events: int
    total_events: int
    paid_orders: int
    revenue_cents: int
    total_tickets_sold: int
    total_bar_orders: int
    bar_revenue_cents: int
    unique_buyers: int
    events: list[dict]


class SupportAIAdminCreateEventIn(BaseModel):
    tenant_id: str = Field(default="default")
    owner_tenant: str
    title: str
    date_text: str | None = None
    city: str | None = None
    venue: str | None = None
    description: str | None = None
    flyer_url: str | None = None
    hero_bg: str | None = None
    visibility: str | None = "public"


class SupportAIAdminTransferEventIn(BaseModel):
    tenant_id: str = Field(default="default")
    event_slug: str
    new_owner_tenant: str


class SupportAIAdminEventPauseIn(BaseModel):
    tenant_id: str = Field(default="default")
    event_slug: str
    is_active: bool


class SupportAIAdminEventSoldOutIn(BaseModel):
    tenant_id: str = Field(default="default")
    event_slug: str
    sold_out: bool


class SupportAIAdminEventServiceChargeIn(BaseModel):
    tenant_id: str = Field(default="default")
    event_slug: str
    service_charge_pct: float


class SupportAIAdminEventDeleteIn(BaseModel):
    tenant_id: str = Field(default="default")
    event_slug: str
    confirm_text: str
    force_delete_paid: bool = False


class SupportAIAdminEventUpdateIn(BaseModel):
    tenant_id: str = Field(default="default")
    event_slug: str
    title: str | None = None
    date_text: str | None = None
    city: str | None = None
    venue: str | None = None
    description: str | None = None
    flyer_url: str | None = None
    hero_bg: str | None = None
    visibility: str | None = None
    active: bool | None = None
    settlement_mode: str | None = None
    mp_collector_id: str | None = None
    payout_alias: str | None = None
    cuit: str | None = None
    contact_phone: str | None = None
    accept_terms: bool | None = None


class SupportAIAdminSaleItemCreateIn(BaseModel):
    tenant_id: str = Field(default="default")
    event_slug: str
    kind: str = "ticket"
    name: str
    price_cents: int
    currency: str = "ARS"
    stock_total: int | None = None
    sort_order: int | None = 0


class SupportAIAdminSaleItemToggleIn(BaseModel):
    tenant_id: str = Field(default="default")
    event_slug: str
    id: int
    active: bool


class SupportAIAdminSaleItemUpdateIn(BaseModel):
    tenant_id: str = Field(default="default")
    event_slug: str
    kind: str = "ticket"
    name: str
    price_cents: int
    currency: str = "ARS"
    stock_total: int | None = None
    sort_order: int | None = 0
    active: bool | None = True


class SupportAIAdminDeleteRequestResolveIn(BaseModel):
    request_id: int
    approve: bool
    resolution_note: str | None = None


def _slugify(value: str) -> str:
    v = (value or "").strip().lower()
    v = re.sub(r"[^a-z0-9]+", "-", v)
    v = re.sub(r"-{2,}", "-", v).strip("-")
    return v or "evento"


def _events_columns() -> set[str]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='events'
            """
        )
        rows = cur.fetchall() or []
        return {str((r or {}).get("column_name") or "") for r in rows if (r or {}).get("column_name")}


def _normalize_service_charge_pct(value: float | int | str | None) -> float:
    try:
        v = float(str(value).replace(",", "."))
    except Exception:
        return 0.15
    if v < 0:
        return 0.15
    # Si vino en formato porcentaje entero (ej: 15), convertir a decimal.
    if v > 1:
        v = v / 100.0
    if v > 1:
        return 0.15
    return round(v, 6)


def _ensure_event_service_charge_column() -> None:
    cols = _events_columns()
    if "service_charge_pct" in cols:
        return
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS service_charge_pct NUMERIC(6,5)")
        cur.execute(
            """
            UPDATE events
            SET service_charge_pct = 0.15
            WHERE service_charge_pct IS NULL OR service_charge_pct < 0 OR service_charge_pct > 1
            """
        )
        cur.execute("ALTER TABLE events ALTER COLUMN service_charge_pct SET DEFAULT 0.15")


def _ensure_event_sold_out_column() -> None:
    cols = _events_columns()
    if "sold_out" in cols:
        return
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS sold_out BOOLEAN")
        cur.execute("UPDATE events SET sold_out = FALSE WHERE sold_out IS NULL")
        cur.execute("ALTER TABLE events ALTER COLUMN sold_out SET DEFAULT FALSE")
        cur.execute("ALTER TABLE events ALTER COLUMN sold_out SET NOT NULL")


def _orders_columns() -> set[str]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='orders'
            """
        )
        rows = cur.fetchall() or []
        return {str((r or {}).get("column_name") or "") for r in rows if (r or {}).get("column_name")}


def _sale_items_columns() -> set[str]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='sale_items'
            """
        )
        rows = cur.fetchall() or []
        return {str((r or {}).get("column_name") or "") for r in rows if (r or {}).get("column_name")}


def _tickets_columns() -> set[str]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='tickets'
            """
        )
        rows = cur.fetchall() or []
        return {str((r or {}).get("column_name") or "") for r in rows if (r or {}).get("column_name")}


def _users_columns() -> set[str]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='users'
            """
        )
        rows = cur.fetchall() or []
        return {str((r or {}).get("column_name") or "") for r in rows if (r or {}).get("column_name")}


def _event_owner_from_row(event_row: dict | None) -> str:
    """Resuelve el owner/productor de un evento de forma compatible con esquemas legacy."""
    if not isinstance(event_row, dict):
        return ""

    for key in ("tenant", "producer", "producer_id"):
        value = str(event_row.get(key) or "").strip()
        if value:
            return value
    return ""


def _ensure_delete_requests_table() -> None:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS support_ai_event_delete_requests (
              id BIGSERIAL PRIMARY KEY,
              tenant_id TEXT NOT NULL,
              event_slug TEXT NOT NULL,
              producer_owner TEXT,
              producer_email TEXT,
              reason TEXT,
              status TEXT NOT NULL DEFAULT 'pending',
              resolution_note TEXT,
              requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              resolved_at TIMESTAMPTZ,
              resolved_by TEXT
            )
            """
        )






def _orders_total_cents_expr(order_cols: set[str], order_alias: str = "o") -> str:
    """Schema-safe gross cents expression across shared orders variants."""

    def _numeric_cents_term(col_name: str) -> str:
        text_expr = f"NULLIF(TRIM({order_alias}.{col_name}::text), '')"
        return (
            "CASE "
            f"WHEN {text_expr} IS NULL THEN NULL "
            f"WHEN {text_expr} ~ '^-?[0-9]+([\\.,][0-9]+)?$' "
            f"THEN ROUND(REPLACE({text_expr}, ',', '.')::numeric * 100)::bigint "
            "ELSE NULL END"
        )

    terms: list[str] = []
    if "total_cents" in order_cols:
        terms.append(f"{order_alias}.total_cents")
    if "total_amount" in order_cols:
        terms.append(_numeric_cents_term("total_amount"))
    if "amount_total" in order_cols:
        terms.append(_numeric_cents_term("amount_total"))
    if "amount" in order_cols:
        terms.append(_numeric_cents_term("amount"))
    return f"COALESCE({', '.join(terms + ['0'])})"

def _extract_email_from_items_json(raw: object) -> str:
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        payload = None

    def _walk(node: object) -> str:
        if isinstance(node, dict):
            direct_candidates = [
                node.get("buyer_email"),
                node.get("email"),
                (node.get("buyer") or {}).get("email") if isinstance(node.get("buyer"), dict) else None,
                (node.get("customer") or {}).get("email") if isinstance(node.get("customer"), dict) else None,
            ]
            for c in direct_candidates:
                v = str(c or "").strip()
                if "@" in v:
                    return v
            for v in node.values():
                found = _walk(v)
                if found:
                    return found
            return ""
        if isinstance(node, list):
            for item in node:
                found = _walk(item)
                if found:
                    return found
            return ""
        v = str(node or "").strip()
        if "@" in v and " " not in v:
            return v
        return ""

    return _walk(payload)


def _extract_buyer_fields_from_items_json(raw: object) -> dict[str, str]:
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        payload = None

    targets = {
        "buyer_name": ("buyer_name", "full_name", "name"),
        "buyer_email": ("buyer_email", "email", "mail"),
        "buyer_phone": ("buyer_phone", "phone", "cellphone", "mobile"),
        "buyer_dni": ("buyer_dni", "dni", "document_number", "document"),
        "buyer_address": ("buyer_address", "address"),
        "buyer_province": ("buyer_province", "province"),
        "buyer_postal_code": ("buyer_postal_code", "postal_code", "zip_code"),
        "buyer_birth_date": ("buyer_birth_date", "birth_date", "date_of_birth"),
    }
    out = {k: "" for k in targets}

    def _store(field: str, value: object):
        if out[field]:
            return
        v = str(value or "").strip()
        if v:
            out[field] = v

    def _walk(node: object):
        if isinstance(node, dict):
            buyer_node = node.get("buyer")
            for field, keys in targets.items():
                for key in keys:
                    if key in node:
                        _store(field, node.get(key))
                    if isinstance(buyer_node, dict) and key in buyer_node:
                        _store(field, buyer_node.get(key))
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(payload)
    return out

def _normalize_owner(value: str) -> str:
    # Permit assigning events to emails without existing account yet.
    # We store a stable slug-like owner key derived from full input.
    v = (value or "").strip().lower()
    return _slugify(v)

_RATE_LIMIT_WINDOW_S = 60
_RATE_LIMIT_MAX = 20
_rate_limit_buckets: dict[str, deque[float]] = defaultdict(deque)
_rate_lock = Lock()


def _feature_enabled() -> bool:
    return os.getenv("SUPPORT_AI_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _staff_emails() -> set[str]:
    raw = (os.getenv("SUPPORT_AI_STAFF_EMAILS") or "").strip()
    if not raw:
        return set()
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def _is_staff_user(request: Request) -> bool:
    user = request.session.get("user") or {}
    email = str(user.get("email") or "").strip().lower()
    if not email:
        return False
    return email in _staff_emails()


def _enforce_rate_limit(key: str) -> None:
    now = time.time()
    with _rate_lock:
        bucket = _rate_limit_buckets[key]
        while bucket and now - bucket[0] > _RATE_LIMIT_WINDOW_S:
            bucket.popleft()
        if len(bucket) >= _RATE_LIMIT_MAX:
            raise HTTPException(status_code=429, detail="Rate limit excedido para soporte IA")
        bucket.append(now)


def get_support_ai_service() -> SupportAIService:
    return SupportAIService()


@router.get("/ai/status", response_model=SupportAIStatusResponse)
def support_ai_status(request: Request) -> SupportAIStatusResponse:
    enabled = _feature_enabled()
    is_staff = _is_staff_user(request)
    return SupportAIStatusResponse(
        enabled=enabled,
        is_staff=is_staff,
        model=(os.getenv("SUPPORT_AI_MODEL") or "gpt-5-mini") if enabled else None,
        has_openai_key=bool((os.getenv("OPENAI_API_KEY") or "").strip()),
        has_vector_store=bool((os.getenv("OPENAI_VECTOR_STORE_ID") or "").strip()),
    )


@router.get("/ai/admin/dashboard", response_model=SupportAIAdminDashboardResponse)
def support_ai_admin_dashboard(request: Request, tenant_id: str = "default", event_slug: str | None = None) -> SupportAIAdminDashboardResponse:
    if not _feature_enabled():
        raise HTTPException(status_code=503, detail="Support AI deshabilitado")
    if not _is_staff_user(request):
        raise HTTPException(status_code=403, detail="Support AI solo disponible para staff")

    ev_slug = (event_slug or "").strip() or None
    order_cols = _orders_columns()
    has_buyer_email = "buyer_email" in order_cols
    has_source = "source" in order_cols
    has_bar_slug = "bar_slug" in order_cols
    has_order_kind = "order_kind" in order_cols
    has_kind = "kind" in order_cols

    ecols = _events_columns()
    has_sold_out = "sold_out" in ecols

    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
              COUNT(*) FILTER (WHERE active=TRUE)::bigint AS active_events,
              COUNT(*)::bigint AS total_events
            FROM events
            WHERE tenant_id=%s
            """,
            (tenant_id,),
        )
        events_row = cur.fetchone() or {}

        where_filter = "AND o.event_slug=%s" if ev_slug else ""
        args_filter = (tenant_id, ev_slug) if ev_slug else (tenant_id,)

        cur.execute(
            f"""
            SELECT
              COUNT(*) FILTER (WHERE o.status ILIKE 'PAID')::bigint AS paid_orders,
              COALESCE(SUM(COALESCE(o.total_cents, ROUND(o.total_amount * 100)::bigint)) FILTER (WHERE o.status ILIKE 'PAID'),0)::bigint AS revenue_cents
            FROM orders o
            WHERE o.tenant_id=%s
              {where_filter}
            """,
            args_filter,
        )
        orders_row = cur.fetchone() or {}

        ticket_filter = "AND t.event_slug=%s" if ev_slug else ""
        ticket_args = (tenant_id, ev_slug) if ev_slug else (tenant_id,)
        cur.execute(
            f"""
            SELECT COUNT(*)::bigint AS total_tickets_sold
            FROM tickets t
            WHERE t.tenant_id=%s
              AND COALESCE(t.status,'') NOT ILIKE 'revoked'
              {ticket_filter}
            """,
            ticket_args,
        )
        tickets_row = cur.fetchone() or {}

        bar_predicates = []
        if has_source:
            bar_predicates.append("COALESCE(source,'')='bar' OR COALESCE(source,'') ILIKE 'barra'")
        if has_bar_slug:
            bar_predicates.append("bar_slug IS NOT NULL")
        if has_order_kind:
            bar_predicates.append("COALESCE(order_kind,'') ILIKE 'bar' OR COALESCE(order_kind,'') ILIKE 'barra'")
        if has_kind:
            bar_predicates.append("COALESCE(kind,'') ILIKE 'bar' OR COALESCE(kind,'') ILIKE 'barra'")
        bar_where = " OR ".join(bar_predicates) if bar_predicates else "FALSE"

        cur.execute(
            f"""
            SELECT
              COUNT(*) FILTER (WHERE o.status ILIKE 'PAID')::bigint AS total_bar_orders,
              COALESCE(SUM(COALESCE(o.total_cents, ROUND(o.total_amount * 100)::bigint)) FILTER (WHERE o.status ILIKE 'PAID'),0)::bigint AS bar_revenue_cents
            FROM orders o
            WHERE o.tenant_id=%s
              {where_filter}
              AND ({bar_where})
            """,
            args_filter,
        )
        bar_row = cur.fetchone() or {}

        if has_buyer_email:
            cur.execute(
                f"""
                SELECT COUNT(DISTINCT lower(o.buyer_email))::bigint AS unique_buyers
                FROM orders o
                WHERE o.tenant_id=%s
                  AND o.status ILIKE 'PAID'
                  AND o.buyer_email IS NOT NULL
                  AND o.buyer_email <> ''
                  {where_filter}
                """,
                args_filter,
            )
            buyers_row = cur.fetchone() or {}
            unique_buyers = int(buyers_row.get("unique_buyers") or 0)
        else:
            unique_buyers = 0

        event_where = "AND e.slug=%s" if ev_slug else ""
        event_args = (tenant_id, ev_slug) if ev_slug else (tenant_id,)
        sold_out_select = "COALESCE(e.sold_out, FALSE) AS sold_out_manual," if has_sold_out else "FALSE AS sold_out_manual,"
        cur.execute(
            f"""
            SELECT
              e.slug,
              e.title,
              {sold_out_select}
              COUNT(t.id)::bigint AS tickets_sold,
              COALESCE(SUM(CASE WHEN COALESCE(si.kind,'') ILIKE 'barra' THEN 0 ELSE COALESCE(si.stock_total,0) END),0)::bigint AS ticket_stock_total
            FROM events e
            LEFT JOIN tickets t ON t.tenant_id=e.tenant_id AND t.event_slug=e.slug AND COALESCE(t.status,'') NOT ILIKE 'revoked'
            LEFT JOIN sale_items si ON si.event_slug=e.slug AND si.tenant=e.tenant AND COALESCE(si.active, TRUE)=TRUE
            WHERE e.tenant_id=%s
              {event_where}
            GROUP BY e.slug, e.title
            ORDER BY tickets_sold DESC, e.title ASC
            LIMIT 200
            """,
            event_args,
        )
        event_rows = cur.fetchall() or []

        # enrich with revenue split from orders
        event_map: dict[str, dict] = {}
        for r in event_rows:
            slug = str((r or {}).get("slug") or "")
            event_map[slug] = {
                "slug": slug,
                "title": (r or {}).get("title") or slug,
                "sold_out_manual": bool((r or {}).get("sold_out_manual")),
                "tickets_sold": int((r or {}).get("tickets_sold") or 0),
                "ticket_stock_total": int((r or {}).get("ticket_stock_total") or 0),
                "sold_out": False,
                "ticket_revenue_cents": 0,
                "bar_revenue_cents": 0,
            }

        cur.execute(
            f"""
            SELECT
              o.event_slug,
              COALESCE(SUM(COALESCE(o.total_cents, ROUND(o.total_amount * 100)::bigint)) FILTER (WHERE o.status ILIKE 'PAID'),0)::bigint AS total_revenue,
              COALESCE(SUM(COALESCE(o.total_cents, ROUND(o.total_amount * 100)::bigint)) FILTER (WHERE o.status ILIKE 'PAID' AND ({bar_where})),0)::bigint AS bar_revenue
            FROM orders o
            WHERE o.tenant_id=%s
              {where_filter}
            GROUP BY o.event_slug
            """,
            args_filter,
        )
        for rr in (cur.fetchall() or []):
            slug = str((rr or {}).get("event_slug") or "")
            if not slug:
                continue
            bucket = event_map.setdefault(
                slug,
                {
                    "slug": slug,
                    "title": slug,
                    "tickets_sold": 0,
                    "ticket_stock_total": 0,
                    "sold_out": False,
                    "ticket_revenue_cents": 0,
                    "bar_revenue_cents": 0,
                },
            )
            total_rev = int((rr or {}).get("total_revenue") or 0)
            bar_rev = int((rr or {}).get("bar_revenue") or 0)
            bucket["bar_revenue_cents"] = bar_rev
            bucket["ticket_revenue_cents"] = max(0, total_rev - bar_rev)

    for item in event_map.values():
        total_stock = int(item.get("ticket_stock_total") or 0)
        sold = int(item.get("tickets_sold") or 0)
        item["sold_out"] = bool(item.get("sold_out_manual")) or bool(total_stock > 0 and sold >= total_stock)

    events_out = sorted(
        event_map.values(),
        key=lambda x: (-(x.get("tickets_sold") or 0), -(x.get("ticket_revenue_cents") or 0), x.get("title") or ""),
    )

    return SupportAIAdminDashboardResponse(
        tenant_id=tenant_id,
        event_filter=ev_slug,
        active_events=int(events_row.get("active_events") or 0),
        total_events=int(events_row.get("total_events") or 0),
        paid_orders=int(orders_row.get("paid_orders") or 0),
        revenue_cents=int(orders_row.get("revenue_cents") or 0),
        total_tickets_sold=int(tickets_row.get("total_tickets_sold") or 0),
        total_bar_orders=int(bar_row.get("total_bar_orders") or 0),
        bar_revenue_cents=int(bar_row.get("bar_revenue_cents") or 0),
        unique_buyers=unique_buyers,
        events=events_out,
    )


@router.get("/ai/admin/events")
def support_ai_admin_events(request: Request, tenant_id: str = "default"):
    if not _feature_enabled():
        raise HTTPException(status_code=503, detail="Support AI deshabilitado")
    if not _is_staff_user(request):
        raise HTTPException(status_code=403, detail="Support AI solo disponible para staff")

    ecols = _events_columns()

    select_fields = [
        "e.slug",
        "e.title",
        "e.tenant",
        "e.producer",
        "e.active",
        "e.city",
        "e.venue",
        "e.date_text",
    ]

    if "settlement_mode" in ecols:
        select_fields.append("e.settlement_mode")
    if "mp_collector_id" in ecols:
        select_fields.append("e.mp_collector_id")
    if "payout_alias" in ecols:
        select_fields.append("e.payout_alias")
    if "service_charge_pct" in ecols:
        select_fields.append("e.service_charge_pct")

    sold_out_expr = (
        "(COALESCE(e.sold_out, FALSE) OR (COALESCE(si.stock_total,0) > 0 AND COALESCE(t.sold,0) >= COALESCE(si.stock_total,0))) AS sold_out"
        if "sold_out" in ecols
        else "(COALESCE(si.stock_total,0) > 0 AND COALESCE(t.sold,0) >= COALESCE(si.stock_total,0)) AS sold_out"
    )
    if "sold_out" in ecols:
        select_fields.append("COALESCE(e.sold_out, FALSE) AS sold_out_manual")
    select_fields.extend(
        [
            "COALESCE(t.sold,0)::bigint AS tickets_sold",
            "COALESCE(si.stock_total,0)::bigint AS ticket_stock_total",
            sold_out_expr,
        ]
    )

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT
              {', '.join(select_fields)}
            FROM events e
            LEFT JOIN (
              SELECT tenant_id, event_slug, COUNT(*)::bigint AS sold
              FROM tickets
              WHERE COALESCE(status,'') NOT ILIKE 'revoked'
              GROUP BY tenant_id, event_slug
            ) t ON t.tenant_id=e.tenant_id AND t.event_slug=e.slug
            LEFT JOIN (
              SELECT tenant, event_slug,
                     COALESCE(SUM(CASE WHEN COALESCE(kind,'') ILIKE 'barra' THEN 0 ELSE COALESCE(stock_total,0) END),0)::bigint AS stock_total
              FROM sale_items
              WHERE COALESCE(active, TRUE)=TRUE
              GROUP BY tenant, event_slug
            ) si ON si.tenant=e.tenant AND si.event_slug=e.slug
            WHERE e.tenant_id=%s
            ORDER BY e.created_at DESC NULLS LAST, e.slug ASC
            LIMIT 300
            """,
            (tenant_id,),
        )
        rows = cur.fetchall() or []

    for row in rows:
        mode = str((row or {}).get("settlement_mode") or "").strip().lower()
        row["settlement_mode"] = "mp_split" if mode == "mp_split" else "manual_transfer"
        raw_pct = (row or {}).get("service_charge_pct")
        row["service_charge_pct"] = _normalize_service_charge_pct(raw_pct)

    return {"ok": True, "events": rows}


@router.post("/ai/admin/events/service-charge")
def support_ai_admin_update_event_service_charge(payload: SupportAIAdminEventServiceChargeIn, request: Request):
    if not _feature_enabled():
        raise HTTPException(status_code=503, detail="Support AI deshabilitado")
    if not _is_staff_user(request):
        raise HTTPException(status_code=403, detail="Support AI solo disponible para staff")

    tenant_id = (payload.tenant_id or "default").strip() or "default"
    event_slug = (payload.event_slug or "").strip()
    if not event_slug:
        raise HTTPException(status_code=400, detail="event_slug requerido")

    pct = _normalize_service_charge_pct(payload.service_charge_pct)

    _ensure_event_service_charge_column()
    ecols = _events_columns()
    if "service_charge_pct" not in ecols:
        raise HTTPException(status_code=400, detail="events.service_charge_pct_missing")

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE events
            SET service_charge_pct=%s
            WHERE tenant_id=%s AND slug=%s
            RETURNING slug, service_charge_pct
            """,
            (pct, tenant_id, event_slug),
        )
        row = cur.fetchone() or {}
        if not row:
            raise HTTPException(status_code=404, detail="event_not_found")

    return {
        "ok": True,
        "event_slug": row.get("slug") or event_slug,
        "service_charge_pct": _normalize_service_charge_pct(row.get("service_charge_pct")),
    }


@router.post("/ai/admin/events/create")
def support_ai_admin_create_event(payload: SupportAIAdminCreateEventIn, request: Request):
    if not _feature_enabled():
        raise HTTPException(status_code=503, detail="Support AI deshabilitado")
    if not _is_staff_user(request):
        raise HTTPException(status_code=403, detail="Support AI solo disponible para staff")

    cols = _events_columns()
    owner = _normalize_owner(payload.owner_tenant)
    tenant_id = (payload.tenant_id or "default").strip() or "default"
    base_slug = _slugify(payload.title)

    with get_conn() as conn:
        cur = conn.cursor()
        slug = base_slug
        i = 2
        while True:
            cur.execute("SELECT 1 FROM events WHERE tenant_id=%s AND slug=%s LIMIT 1", (tenant_id, slug))
            if not cur.fetchone():
                break
            slug = f"{base_slug}-{i}"
            i += 1

        data = {
            "slug": slug,
            "title": payload.title,
            "tenant_id": tenant_id,
            "tenant": owner,
            "producer": owner,
            "active": True,
            "visibility": (payload.visibility or "public"),
            "date_text": payload.date_text,
            "city": payload.city,
            "venue": payload.venue,
            "description": payload.description,
            "flyer_url": payload.flyer_url,
            "hero_bg": payload.hero_bg,
        }
        use_cols = [c for c in data.keys() if c in cols]
        values = [data[c] for c in use_cols]
        placeholders = ", ".join(["%s"] * len(use_cols))
        cur.execute(
            f"INSERT INTO events ({', '.join(use_cols)}) VALUES ({placeholders}) RETURNING slug",
            values,
        )
        created = cur.fetchone() or {}
    return {"ok": True, "slug": created.get("slug") or slug, "owner": owner, "tenant_id": tenant_id}


@router.post("/ai/admin/events/update")
def support_ai_admin_update_event(payload: SupportAIAdminEventUpdateIn, request: Request):
    if not _feature_enabled():
        raise HTTPException(status_code=503, detail="Support AI deshabilitado")
    if not _is_staff_user(request):
        raise HTTPException(status_code=403, detail="Support AI solo disponible para staff")

    tenant_id = (payload.tenant_id or "default").strip() or "default"
    event_slug = (payload.event_slug or "").strip()
    if not event_slug:
        raise HTTPException(status_code=400, detail="event_slug requerido")

    cols = _events_columns()
    updates: dict[str, object] = {}

    if payload.title is not None:
        updates["title"] = str(payload.title).strip() or event_slug
    if payload.date_text is not None:
        updates["date_text"] = payload.date_text
    if payload.city is not None:
        updates["city"] = payload.city
    if payload.venue is not None:
        updates["venue"] = payload.venue
    if payload.description is not None:
        updates["description"] = payload.description
    if payload.flyer_url is not None:
        updates["flyer_url"] = payload.flyer_url
    if payload.hero_bg is not None:
        updates["hero_bg"] = payload.hero_bg
    if payload.visibility is not None:
        updates["visibility"] = payload.visibility if payload.visibility in {"public", "unlisted"} else "public"
    if payload.active is not None:
        updates["active"] = bool(payload.active)
    if payload.settlement_mode is not None:
        updates["settlement_mode"] = "mp_split" if str(payload.settlement_mode) == "mp_split" else "manual_transfer"
    if payload.mp_collector_id is not None:
        updates["mp_collector_id"] = payload.mp_collector_id
    if payload.payout_alias is not None:
        updates["payout_alias"] = payload.payout_alias
    if payload.cuit is not None:
        updates["cuit"] = payload.cuit
    if payload.contact_phone is not None:
        updates["contact_phone"] = payload.contact_phone
    if payload.accept_terms is not None:
        updates["accept_terms"] = bool(payload.accept_terms)

    fields = [k for k in updates.keys() if k in cols]
    if not fields:
        raise HTTPException(status_code=400, detail="no_valid_fields_to_update")

    set_expr = ", ".join([f"{k}=%s" for k in fields])
    values = [updates[k] for k in fields]

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE events SET {set_expr} WHERE tenant_id=%s AND slug=%s RETURNING slug",
            [*values, tenant_id, event_slug],
        )
        row = cur.fetchone() or {}
        if not row:
            raise HTTPException(status_code=404, detail="event_not_found")

    return {"ok": True, "event_slug": row.get("slug") or event_slug, "tenant_id": tenant_id}


@router.post("/ai/admin/events/transfer")
def support_ai_admin_transfer_event(payload: SupportAIAdminTransferEventIn, request: Request):
    if not _feature_enabled():
        raise HTTPException(status_code=503, detail="Support AI deshabilitado")
    if not _is_staff_user(request):
        raise HTTPException(status_code=403, detail="Support AI solo disponible para staff")

    owner = _normalize_owner(payload.new_owner_tenant)
    tenant_id = (payload.tenant_id or "default").strip() or "default"

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE events
            SET tenant=%s, producer=%s
            WHERE tenant_id=%s AND slug=%s
            """,
            (owner, owner, tenant_id, payload.event_slug),
        )
        updated = cur.rowcount

    if not updated:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    return {"ok": True, "event_slug": payload.event_slug, "new_owner": owner, "tenant_id": tenant_id}


@router.post("/ai/admin/events/pause")
def support_ai_admin_pause_event(payload: SupportAIAdminEventPauseIn, request: Request):
    if not _feature_enabled():
        raise HTTPException(status_code=503, detail="Support AI deshabilitado")
    if not _is_staff_user(request):
        raise HTTPException(status_code=403, detail="Support AI solo disponible para staff")

    tenant_id = (payload.tenant_id or "default").strip() or "default"
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE events
            SET active=%s
            WHERE tenant_id=%s AND slug=%s
            """,
            (bool(payload.is_active), tenant_id, payload.event_slug),
        )
        updated = cur.rowcount
    if not updated:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    return {"ok": True, "event_slug": payload.event_slug, "active": bool(payload.is_active), "tenant_id": tenant_id}


@router.post("/ai/admin/events/sold-out")
def support_ai_admin_set_event_sold_out(payload: SupportAIAdminEventSoldOutIn, request: Request):
    if not _feature_enabled():
        raise HTTPException(status_code=503, detail="Support AI deshabilitado")
    if not _is_staff_user(request):
        raise HTTPException(status_code=403, detail="Support AI solo disponible para staff")

    _ensure_event_sold_out_column()
    tenant_id = (payload.tenant_id or "default").strip() or "default"
    event_slug = (payload.event_slug or "").strip()
    if not event_slug:
        raise HTTPException(status_code=400, detail="event_slug requerido")

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE events
               SET sold_out=%s
             WHERE tenant_id=%s AND slug=%s
            """,
            (bool(payload.sold_out), tenant_id, event_slug),
        )
        updated = cur.rowcount
    if not updated:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    return {"ok": True, "event_slug": event_slug, "sold_out": bool(payload.sold_out), "tenant_id": tenant_id}


@router.post("/ai/admin/events/delete")
def support_ai_admin_delete_event(payload: SupportAIAdminEventDeleteIn, request: Request):
    if not _feature_enabled():
        raise HTTPException(status_code=503, detail="Support AI deshabilitado")
    if not _is_staff_user(request):
        raise HTTPException(status_code=403, detail="Support AI solo disponible para staff")

    if (payload.confirm_text or "").strip().upper() != "ELIMINAR":
        raise HTTPException(status_code=400, detail="Confirmación inválida. Escribí ELIMINAR")

    tenant_id = (payload.tenant_id or "default").strip() or "default"
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT slug, tenant FROM events WHERE tenant_id=%s AND slug=%s LIMIT 1", (tenant_id, payload.event_slug))
        event = cur.fetchone() or {}
        if not event:
            raise HTTPException(status_code=404, detail="Evento no encontrado")

        cur.execute(
            """
            SELECT
              COUNT(*)::bigint AS order_count,
              COUNT(*) FILTER (WHERE status ILIKE 'PAID')::bigint AS paid_count
            FROM orders
            WHERE tenant_id=%s AND event_slug=%s
            """,
            (tenant_id, payload.event_slug),
        )
        order_stats = cur.fetchone() or {}
        order_count = int(order_stats.get("order_count") or 0)
        paid_count = int(order_stats.get("paid_count") or 0)
        if order_count > 0 and not bool(payload.force_delete_paid):
            raise HTTPException(
                status_code=409,
                detail="No se puede eliminar: el evento tiene órdenes asociadas. Si es para pruebas, forzá la eliminación.",
            )

        deleted_tickets = 0
        deleted_orders = 0
        if order_count > 0 and bool(payload.force_delete_paid):
            cur.execute("DELETE FROM tickets WHERE tenant_id=%s AND event_slug=%s", (tenant_id, payload.event_slug))
            deleted_tickets = int(cur.rowcount or 0)
            cur.execute("DELETE FROM orders WHERE tenant_id=%s AND event_slug=%s", (tenant_id, payload.event_slug))
            deleted_orders = int(cur.rowcount or 0)

        owner = str(event.get("tenant") or "")
        deleted_sale_items = 0
        if owner:
            cur.execute("DELETE FROM sale_items WHERE tenant=%s AND event_slug=%s", (owner, payload.event_slug))
            deleted_sale_items = int(cur.rowcount or 0)
        cur.execute("DELETE FROM events WHERE tenant_id=%s AND slug=%s", (tenant_id, payload.event_slug))
        deleted = cur.rowcount

    return {
        "ok": True,
        "event_slug": payload.event_slug,
        "deleted": bool(deleted),
        "tenant_id": tenant_id,
        "forced_paid_cleanup": bool(payload.force_delete_paid and order_count > 0),
        "paid_orders_found": paid_count,
        "deleted_counts": {
            "orders": deleted_orders,
            "tickets": deleted_tickets,
            "sale_items": deleted_sale_items,
            "events": int(deleted or 0),
        },
    }


@router.get("/ai/admin/sale-items")
def support_ai_admin_list_sale_items(request: Request, tenant_id: str = "default", event_slug: str = ""):
    if not _feature_enabled():
        raise HTTPException(status_code=503, detail="Support AI deshabilitado")
    if not _is_staff_user(request):
        raise HTTPException(status_code=403, detail="Support AI solo disponible para staff")
    if not event_slug:
        raise HTTPException(status_code=400, detail="event_slug requerido")

    cols = _sale_items_columns()

    def _sel(col: str, fallback_sql: str) -> str:
        return col if col in cols else f"{fallback_sql} AS {col}"

    select_sql = ", ".join(
        [
            _sel("id", "0"),
            _sel("tenant", "''::text"),
            _sel("event_slug", "''::text"),
            _sel("name", "''::text"),
            _sel("kind", "'ticket'::text"),
            _sel("price_cents", "0"),
            _sel("currency", "'ARS'::text"),
            _sel("stock_total", "0"),
            _sel("stock_sold", "0"),
            _sel("active", "TRUE"),
            _sel("display_order", "0"),
        ]
    )

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT tenant, producer, producer_id
            FROM events
            WHERE tenant_id=%s AND slug=%s
            LIMIT 1
            """,
            (tenant_id, event_slug),
        )
        event = cur.fetchone() or {}
        owner = _event_owner_from_row(event)
        if not owner:
            return {"ok": True, "items": []}

        cur.execute(
            f"""
            SELECT {select_sql}
            FROM sale_items
            WHERE tenant=%s AND event_slug=%s
            ORDER BY COALESCE(display_order, 0) ASC, id ASC
            """,
            (owner, event_slug),
        )
        rows = cur.fetchall() or []
    return {"ok": True, "items": rows}


@router.post("/ai/admin/sale-items/create")
def support_ai_admin_create_sale_item(payload: SupportAIAdminSaleItemCreateIn, request: Request):
    if not _feature_enabled():
        raise HTTPException(status_code=503, detail="Support AI deshabilitado")
    if not _is_staff_user(request):
        raise HTTPException(status_code=403, detail="Support AI solo disponible para staff")

    tenant_id = (payload.tenant_id or "default").strip() or "default"
    item_name = (payload.name or "").strip()
    if not item_name:
        raise HTTPException(status_code=400, detail="name requerido")
    if int(payload.price_cents) < 0:
        raise HTTPException(status_code=400, detail="price_cents inválido")

    cols = _sale_items_columns()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT tenant, producer, producer_id
            FROM events
            WHERE tenant_id=%s AND slug=%s
            LIMIT 1
            """,
            (tenant_id, payload.event_slug),
        )
        event = cur.fetchone() or {}
        owner = _event_owner_from_row(event)
        if not owner:
            raise HTTPException(status_code=404, detail="Evento no encontrado")

        data = {
            "tenant": owner,
            "event_slug": payload.event_slug,
            "name": item_name,
            "kind": (payload.kind or "ticket"),
            "price_cents": int(payload.price_cents),
            "currency": payload.currency or "ARS",
            "stock_total": payload.stock_total,
            "display_order": payload.sort_order if payload.sort_order is not None else 0,
            "active": True,
        }
        use_cols = [c for c in data.keys() if c in cols and data.get(c) is not None]
        values = [data[c] for c in use_cols]
        placeholders = ", ".join(["%s"] * len(use_cols))
        cur.execute(
            f"INSERT INTO sale_items ({', '.join(use_cols)}) VALUES ({placeholders}) RETURNING id",
            values,
        )
        row = cur.fetchone() or {}
    return {"ok": True, "id": row.get("id"), "event_slug": payload.event_slug, "producer": owner}


@router.post("/ai/admin/sale-items/toggle")
def support_ai_admin_toggle_sale_item(payload: SupportAIAdminSaleItemToggleIn, request: Request):
    if not _feature_enabled():
        raise HTTPException(status_code=503, detail="Support AI deshabilitado")
    if not _is_staff_user(request):
        raise HTTPException(status_code=403, detail="Support AI solo disponible para staff")

    tenant_id = (payload.tenant_id or "default").strip() or "default"
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT tenant, producer, producer_id
            FROM events
            WHERE tenant_id=%s AND slug=%s
            LIMIT 1
            """,
            (tenant_id, payload.event_slug),
        )
        event = cur.fetchone() or {}
        owner = _event_owner_from_row(event)
        if not owner:
            raise HTTPException(status_code=404, detail="Evento no encontrado")

        cur.execute(
            """
            UPDATE sale_items
            SET active=%s
            WHERE id=%s AND tenant=%s AND event_slug=%s
            """,
            (bool(payload.active), int(payload.id), owner, payload.event_slug),
        )
        updated = cur.rowcount

    if not updated:
        raise HTTPException(status_code=404, detail="Item no encontrado")
    return {"ok": True, "id": payload.id, "active": bool(payload.active)}


@router.put("/ai/admin/sale-items/{sale_item_id}")
def support_ai_admin_update_sale_item(
    sale_item_id: int,
    payload: SupportAIAdminSaleItemUpdateIn,
    request: Request,
    tenant_id: str = "default",
    event_slug: str = "",
):
    if not _feature_enabled():
        raise HTTPException(status_code=503, detail="Support AI deshabilitado")
    if not _is_staff_user(request):
        raise HTTPException(status_code=403, detail="Support AI solo disponible para staff")
    if sale_item_id <= 0:
        raise HTTPException(status_code=400, detail="sale_item_id inválido")

    owner_tenant = (payload.tenant_id or tenant_id or "default").strip() or "default"
    owner_event_slug = (payload.event_slug or event_slug or "").strip()
    if not owner_event_slug:
        raise HTTPException(status_code=400, detail="event_slug requerido")
    item_name = (payload.name or "").strip()
    if not item_name:
        raise HTTPException(status_code=400, detail="name requerido")
    if int(payload.price_cents) < 0:
        raise HTTPException(status_code=400, detail="price_cents inválido")

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT tenant, producer, producer_id
            FROM events
            WHERE tenant_id=%s AND slug=%s
            LIMIT 1
            """,
            (owner_tenant, owner_event_slug),
        )
        event = cur.fetchone() or {}
        owner = _event_owner_from_row(event)
        if not owner:
            raise HTTPException(status_code=404, detail="Evento no encontrado")

        cur.execute(
            """
            UPDATE sale_items
               SET name=%s,
                   kind=%s,
                   price_cents=%s,
                   currency=%s,
                   stock_total=%s,
                   active=%s,
                   display_order=%s
             WHERE id=%s AND tenant=%s AND event_slug=%s
             RETURNING id
            """,
            (
                item_name,
                (payload.kind or "ticket").strip() or "ticket",
                int(payload.price_cents),
                payload.currency or "ARS",
                payload.stock_total,
                bool(payload.active) if payload.active is not None else True,
                payload.sort_order if payload.sort_order is not None else 0,
                int(sale_item_id),
                owner,
                owner_event_slug,
            ),
        )
        row = cur.fetchone() or {}

    updated_id = row.get("id")
    if not updated_id:
        raise HTTPException(status_code=404, detail="Item no encontrado")
    return {"ok": True, "id": int(updated_id), "event_slug": owner_event_slug}


@router.delete("/ai/admin/sale-items/{sale_item_id}")
def support_ai_admin_delete_sale_item(sale_item_id: int, request: Request, tenant_id: str = "default", event_slug: str = ""):
    if not _feature_enabled():
        raise HTTPException(status_code=503, detail="Support AI deshabilitado")
    if not _is_staff_user(request):
        raise HTTPException(status_code=403, detail="Support AI solo disponible para staff")
    if sale_item_id <= 0:
        raise HTTPException(status_code=400, detail="sale_item_id inválido")
    if not event_slug:
        raise HTTPException(status_code=400, detail="event_slug requerido")

    tenant_id = (tenant_id or "default").strip() or "default"

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT tenant, producer, producer_id
            FROM events
            WHERE tenant_id=%s AND slug=%s
            LIMIT 1
            """,
            (tenant_id, event_slug),
        )
        event = cur.fetchone() or {}
        owner = _event_owner_from_row(event)
        if not owner:
            raise HTTPException(status_code=404, detail="Evento no encontrado")

        cur.execute(
            """
            DELETE FROM sale_items
            WHERE id=%s AND tenant=%s AND event_slug=%s
            """,
            (int(sale_item_id), owner, event_slug),
        )
        deleted = cur.rowcount

    if not deleted:
        raise HTTPException(status_code=404, detail="Item no encontrado")

    return {"ok": True, "id": int(sale_item_id), "deleted": True, "event_slug": event_slug}


@router.get("/ai/admin/bar-sales")
def support_ai_admin_bar_sales(request: Request, tenant_id: str = "default", event_slug: str = "", limit: int = 100):
    if not _feature_enabled():
        raise HTTPException(status_code=503, detail="Support AI deshabilitado")
    if not _is_staff_user(request):
        raise HTTPException(status_code=403, detail="Support AI solo disponible para staff")
    if not event_slug:
        raise HTTPException(status_code=400, detail="event_slug requerido")

    limit = max(1, min(int(limit or 100), 500))
    order_cols = _orders_columns()
    users_cols = _users_columns()

    auth_subject_expr = "NULLIF(TRIM(o.auth_subject::text), '')" if "auth_subject" in order_cols else "NULL::text"
    users_join = ""
    if "auth_subject" in order_cols and "auth_subject" in users_cols and "email" in users_cols:
        if "tenant_id" in users_cols:
            users_join = "LEFT JOIN users u ON u.auth_subject::text = o.auth_subject::text AND u.tenant_id=%s"
        else:
            users_join = "LEFT JOIN users u ON u.auth_subject::text = o.auth_subject::text"

    email_candidates = []
    if "buyer_email" in order_cols:
        email_candidates.append("NULLIF(TRIM(o.buyer_email::text), '')")
    if users_join:
        email_candidates.append("NULLIF(TRIM(u.email::text), '')")
    if "customer_label" in order_cols:
        email_candidates.append("NULLIF(TRIM(o.customer_label::text), '')")
    if "auth_subject" in order_cols:
        email_candidates.append("NULLIF(TRIM(o.auth_subject::text), '')")
    if "buyer_name" in order_cols:
        email_candidates.append("NULLIF(TRIM(o.buyer_name::text), '')")
    email_expr = f"COALESCE({', '.join(email_candidates)}, '')" if email_candidates else "''"
    items_expr = "o.items_json" if "items_json" in order_cols else "NULL::text"
    customer_label_expr = "COALESCE(o.customer_label::text, '')" if "customer_label" in order_cols else "''"
    user_email_expr = "COALESCE(u.email::text, '')" if users_join else "''"
    user_name_expr = "COALESCE(u.name::text, '')" if (users_join and "name" in users_cols) else "''"
    total_cents_expr = _orders_total_cents_expr(order_cols, "o")

    with get_conn() as conn:
        cur = conn.cursor()
        params = []
        if users_join and "tenant_id" in users_cols:
            params.append(tenant_id)
        params.extend([tenant_id, event_slug, limit])
        cur.execute(
            f"""
            SELECT o.id, o.created_at,
                   COALESCE(o.status, '') AS status,
                   {email_expr} AS buyer_email,
                   {auth_subject_expr} AS auth_subject,
                   {total_cents_expr}::bigint AS total_cents,
                   o.source, o.bar_slug, o.order_kind, o.kind,
                   {items_expr} AS items_json,
                   {customer_label_expr} AS customer_label,
                   {user_email_expr} AS user_email,
                   {user_name_expr} AS user_name
            FROM orders o
            {users_join}
            WHERE o.tenant_id=%s
              AND o.event_slug=%s
              AND (o.status ILIKE 'PAID' OR o.status ILIKE 'APPROVED' OR o.status ILIKE 'AUTHORIZED')
              AND (
                    COALESCE(source,'')='bar'
                 OR COALESCE(source,'') ILIKE 'barra'
                 OR bar_slug IS NOT NULL
                 OR COALESCE(order_kind,'') ILIKE 'bar'
                 OR COALESCE(order_kind,'') ILIKE 'barra'
                 OR COALESCE(kind,'') ILIKE 'bar'
                 OR COALESCE(kind,'') ILIKE 'barra'
              )
            ORDER BY o.created_at DESC NULLS LAST, o.id DESC
            LIMIT %s
            """,
            tuple(params),
        )
        rows = cur.fetchall() or []

    enriched = []
    for r in rows:
        row = dict(r or {})
        email = str(row.get("buyer_email") or "").strip()
        user_email = str(row.get("user_email") or "").strip()
        customer_label = str(row.get("customer_label") or "").strip()

        if (not email or "@" not in email) and (user_email and "@" in user_email):
            email = user_email
        if (not email or "@" not in email) and (customer_label and "@" in customer_label):
            email = customer_label
        if not email or "@" not in email:
            extracted = _extract_email_from_items_json(row.get("items_json"))
            if extracted:
                email = extracted
        row["buyer_email"] = email

        buyer_name = str(row.get("buyer_name") or "").strip()
        user_name = str(row.get("user_name") or "").strip()
        if (not buyer_name or buyer_name.lower() in {"cliente", "-"}) and user_name:
            row["buyer_name"] = user_name

        enriched.append(row)

    total_cents = sum(int((r or {}).get("total_cents") or 0) for r in enriched)
    return {"ok": True, "event_slug": event_slug, "orders": enriched, "orders_count": len(enriched), "bar_revenue_cents": total_cents}


@router.get("/ai/admin/sold-tickets")
def support_ai_admin_sold_tickets(request: Request, tenant_id: str = "default", event_slug: str = "", limit: int = 1000):
    if not _feature_enabled():
        raise HTTPException(status_code=503, detail="Support AI deshabilitado")
    if not _is_staff_user(request):
        raise HTTPException(status_code=403, detail="Support AI solo disponible para staff")
    if not event_slug:
        raise HTTPException(status_code=400, detail="event_slug requerido")

    limit = max(1, min(int(limit or 1000), 5000))
    order_cols = _orders_columns()
    ticket_cols = _tickets_columns()
    users_cols = _users_columns()

    name_expr = "COALESCE(o.buyer_name, '')" if "buyer_name" in order_cols else "''"

    users_join = ""
    if "auth_subject" in order_cols and "auth_subject" in users_cols and "email" in users_cols:
        if "tenant_id" in users_cols:
            users_join = "LEFT JOIN users u ON u.auth_subject::text = o.auth_subject::text AND u.tenant_id=%s"
        else:
            users_join = "LEFT JOIN users u ON u.auth_subject::text = o.auth_subject::text"

    email_candidates = []
    if "buyer_email" in order_cols:
        email_candidates.append("NULLIF(TRIM(o.buyer_email), '')")
    if "customer_label" in order_cols:
        email_candidates.append("NULLIF(TRIM(o.customer_label), '')")
    if "auth_subject" in order_cols:
        email_candidates.append("NULLIF(TRIM(o.auth_subject), '')")
    if users_join:
        email_candidates.append("NULLIF(TRIM(u.email::text), '')")
    if "buyer_name" in order_cols:
        email_candidates.append("NULLIF(TRIM(o.buyer_name), '')")
    email_expr = f"COALESCE({', '.join(email_candidates)}, '')" if email_candidates else "''"

    phone_candidates = []
    if "buyer_phone" in order_cols:
        phone_candidates.append("NULLIF(TRIM(o.buyer_phone), '')")
    if "buyer_phone" in ticket_cols:
        phone_candidates.append("NULLIF(TRIM(t.buyer_phone), '')")
    if "phone" in ticket_cols:
        phone_candidates.append("NULLIF(TRIM(t.phone), '')")
    if "cellphone" in ticket_cols:
        phone_candidates.append("NULLIF(TRIM(t.cellphone), '')")
    phone_expr = f"COALESCE({', '.join(phone_candidates)}, '')" if phone_candidates else "''"

    dni_candidates = []
    if "buyer_dni" in order_cols:
        dni_candidates.append("NULLIF(TRIM(o.buyer_dni), '')")
    if "buyer_dni" in ticket_cols:
        dni_candidates.append("NULLIF(TRIM(t.buyer_dni), '')")
    if "document_number" in ticket_cols:
        dni_candidates.append("NULLIF(TRIM(t.document_number), '')")
    if "dni" in ticket_cols:
        dni_candidates.append("NULLIF(TRIM(t.dni), '')")
    dni_expr = f"COALESCE({', '.join(dni_candidates)}, '')" if dni_candidates else "''"

    address_candidates = []
    if "buyer_address" in order_cols:
        address_candidates.append("NULLIF(TRIM(o.buyer_address), '')")
    if "buyer_address" in ticket_cols:
        address_candidates.append("NULLIF(TRIM(t.buyer_address), '')")
    if "address" in ticket_cols:
        address_candidates.append("NULLIF(TRIM(t.address), '')")
    address_expr = f"COALESCE({', '.join(address_candidates)}, '')" if address_candidates else "''"

    province_candidates = []
    if "buyer_province" in order_cols:
        province_candidates.append("NULLIF(TRIM(o.buyer_province), '')")
    if "buyer_province" in ticket_cols:
        province_candidates.append("NULLIF(TRIM(t.buyer_province), '')")
    if "province" in ticket_cols:
        province_candidates.append("NULLIF(TRIM(t.province), '')")
    province_expr = f"COALESCE({', '.join(province_candidates)}, '')" if province_candidates else "''"

    postal_code_candidates = []
    if "buyer_postal_code" in order_cols:
        postal_code_candidates.append("NULLIF(TRIM(o.buyer_postal_code), '')")
    if "buyer_postal_code" in ticket_cols:
        postal_code_candidates.append("NULLIF(TRIM(t.buyer_postal_code), '')")
    if "postal_code" in ticket_cols:
        postal_code_candidates.append("NULLIF(TRIM(t.postal_code), '')")
    if "zip_code" in ticket_cols:
        postal_code_candidates.append("NULLIF(TRIM(t.zip_code), '')")
    postal_code_expr = f"COALESCE({', '.join(postal_code_candidates)}, '')" if postal_code_candidates else "''"

    birth_date_candidates = []
    if "buyer_birth_date" in order_cols:
        birth_date_candidates.append("NULLIF(TRIM(o.buyer_birth_date::text), '')")
    if "buyer_birth_date" in ticket_cols:
        birth_date_candidates.append("NULLIF(TRIM(t.buyer_birth_date::text), '')")
    if "birth_date" in ticket_cols:
        birth_date_candidates.append("NULLIF(TRIM(t.birth_date::text), '')")
    birth_date_expr = f"COALESCE({', '.join(birth_date_candidates)}, '')" if birth_date_candidates else "''"
    items_expr = "o.items_json" if "items_json" in order_cols else "NULL::text"
    qr_token_expr = "COALESCE(t.qr_token, '')" if "qr_token" in ticket_cols else "''"
    qr_payload_expr = "COALESCE(t.qr_payload::text, '')" if "qr_payload" in ticket_cols else "''"
    used_at_expr = "t.used_at" if "used_at" in ticket_cols else "NULL::timestamptz"
    sold_at_expr = "COALESCE(t.created_at, o.created_at)" if "created_at" in ticket_cols else "o.created_at"

    with get_conn() as conn:
        cur = conn.cursor()
        params: list = []
        if users_join and "tenant_id" in users_cols:
            params.append(tenant_id)
        params.extend([tenant_id, event_slug, limit])
        cur.execute(
            f"""
            SELECT
              t.id::text AS ticket_id,
              COALESCE(t.order_id::text, '') AS order_id,
              COALESCE(t.sale_item_id::text, '') AS sale_item_id,
              COALESCE(t.status, '') AS status,
              {qr_token_expr} AS qr_token,
              {qr_payload_expr} AS qr_payload,
              {used_at_expr} AS used_at,
              {sold_at_expr} AS sold_at,
              {name_expr} AS buyer_name,
              {email_expr} AS buyer_email,
              {phone_expr} AS buyer_phone,
              {dni_expr} AS buyer_dni,
              {address_expr} AS buyer_address,
              {province_expr} AS buyer_province,
              {postal_code_expr} AS buyer_postal_code,
              {birth_date_expr} AS buyer_birth_date,
              {items_expr} AS items_json
            FROM tickets t
            LEFT JOIN orders o ON o.id::text = t.order_id::text
            {users_join}
            WHERE t.tenant_id=%s
              AND t.event_slug=%s
              AND COALESCE(t.status, '') NOT ILIKE 'revoked'
            ORDER BY {sold_at_expr} DESC NULLS LAST, t.id DESC
            LIMIT %s
            """,
            tuple(params),
        )
        rows = cur.fetchall() or []

    tickets = []
    for r in rows:
        row = dict(r or {})
        email = str(row.get("buyer_email") or "").strip()
        fallback = _extract_buyer_fields_from_items_json(row.get("items_json"))

        if not email or "@" not in email:
            email = fallback.get("buyer_email") or _extract_email_from_items_json(row.get("items_json"))
        row["buyer_email"] = email
        row["buyer_name"] = str(row.get("buyer_name") or "").strip() or fallback.get("buyer_name") or ""
        row["buyer_phone"] = str(row.get("buyer_phone") or "").strip() or fallback.get("buyer_phone") or ""
        row["buyer_dni"] = str(row.get("buyer_dni") or "").strip() or fallback.get("buyer_dni") or ""
        row["buyer_address"] = str(row.get("buyer_address") or "").strip() or fallback.get("buyer_address") or ""
        row["buyer_province"] = str(row.get("buyer_province") or "").strip() or fallback.get("buyer_province") or ""
        row["buyer_postal_code"] = str(row.get("buyer_postal_code") or "").strip() or fallback.get("buyer_postal_code") or ""
        row["buyer_birth_date"] = str(row.get("buyer_birth_date") or "").strip() or fallback.get("buyer_birth_date") or ""
        tickets.append(row)

    return {"ok": True, "event_slug": event_slug, "count": len(tickets), "tickets": tickets}


@router.get("/ai/admin/events/delete-requests")
def support_ai_admin_delete_requests(request: Request, tenant_id: str = "default", status: str = "pending"):
    if not _feature_enabled():
        raise HTTPException(status_code=503, detail="Support AI deshabilitado")
    if not _is_staff_user(request):
        raise HTTPException(status_code=403, detail="Support AI solo disponible para staff")

    _ensure_delete_requests_table()
    st = (status or "pending").strip().lower()
    if st not in {"pending", "approved", "rejected", "all"}:
        st = "pending"

    with get_conn() as conn:
        cur = conn.cursor()
        if st == "all":
            cur.execute(
                """
                SELECT id, tenant_id, event_slug, producer_owner, producer_email, reason, status, requested_at, resolved_at, resolved_by, resolution_note
                FROM support_ai_event_delete_requests
                WHERE tenant_id=%s
                ORDER BY requested_at DESC
                LIMIT 200
                """,
                (tenant_id,),
            )
        else:
            cur.execute(
                """
                SELECT id, tenant_id, event_slug, producer_owner, producer_email, reason, status, requested_at, resolved_at, resolved_by, resolution_note
                FROM support_ai_event_delete_requests
                WHERE tenant_id=%s AND status=%s
                ORDER BY requested_at DESC
                LIMIT 200
                """,
                (tenant_id, st),
            )
        rows = cur.fetchall() or []
    return {"ok": True, "requests": rows}


@router.post("/ai/admin/events/delete-requests/resolve")
def support_ai_admin_resolve_delete_request(payload: SupportAIAdminDeleteRequestResolveIn, request: Request):
    if not _feature_enabled():
        raise HTTPException(status_code=503, detail="Support AI deshabilitado")
    if not _is_staff_user(request):
        raise HTTPException(status_code=403, detail="Support AI solo disponible para staff")

    _ensure_delete_requests_table()
    admin_email = str((request.session.get("user") or {}).get("email") or "").strip().lower()

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, tenant_id, event_slug, status
            FROM support_ai_event_delete_requests
            WHERE id=%s
            LIMIT 1
            """,
            (payload.request_id,),
        )
        req = cur.fetchone() or {}
        if not req:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada")
        if str(req.get("status") or "") != "pending":
            raise HTTPException(status_code=409, detail="La solicitud ya fue resuelta")

        tenant_id = str(req.get("tenant_id") or "default")
        event_slug = str(req.get("event_slug") or "")

        if payload.approve:
            cur.execute(
                """
                SELECT
                  COUNT(*)::bigint AS order_count,
                  COUNT(*) FILTER (WHERE status ILIKE 'PAID')::bigint AS paid_count
                FROM orders
                WHERE tenant_id=%s AND event_slug=%s
                """,
                (tenant_id, event_slug),
            )
            order_stats = cur.fetchone() or {}
            order_count = int(order_stats.get("order_count") or 0)
            if order_count > 0:
                raise HTTPException(status_code=409, detail="No se puede eliminar por solicitud: el evento tiene órdenes asociadas.")

            cur.execute("SELECT tenant FROM events WHERE tenant_id=%s AND slug=%s LIMIT 1", (tenant_id, event_slug))
            event = cur.fetchone() or {}
            owner = str(event.get("tenant") or "")
            if owner:
                cur.execute("DELETE FROM sale_items WHERE tenant=%s AND event_slug=%s", (owner, event_slug))
            cur.execute("DELETE FROM events WHERE tenant_id=%s AND slug=%s", (tenant_id, event_slug))

        new_status = "approved" if payload.approve else "rejected"
        cur.execute(
            """
            UPDATE support_ai_event_delete_requests
            SET status=%s, resolution_note=%s, resolved_at=NOW(), resolved_by=%s
            WHERE id=%s
            """,
            (new_status, payload.resolution_note, admin_email, payload.request_id),
        )

    return {"ok": True, "request_id": payload.request_id, "status": new_status}


@router.post("/ai/chat", response_model=SupportAIChatResponse)
def support_ai_chat(payload: SupportAIChatRequest, request: Request) -> SupportAIChatResponse:
    if not _feature_enabled():
        raise HTTPException(status_code=503, detail="Support AI deshabilitado")

    if not _is_staff_user(request):
        raise HTTPException(status_code=403, detail="Support AI solo disponible para staff")

    client_ip = request.client.host if request.client else "unknown"
    _enforce_rate_limit(client_ip)

    service = get_support_ai_service()
    try:
        return service.chat(payload)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=502, detail="support_ai_error")
