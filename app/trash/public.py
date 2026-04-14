from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from app.db import get_db

router = APIRouter(prefix="/api/public", tags=["public"])


def _coerce_event_row(row: Dict[str, Any]) -> Dict[str, Any]:
    # Make the response stable for the frontend.
    r = dict(row)
    # Common aliases
    if "flyer_url" not in r and "flyer" in r:
        r["flyer_url"] = r.get("flyer")
    if "venue" not in r and "location" in r:
        r["venue"] = r.get("location")
    return r


def _load_event(tenant_id: str, slug: str) -> Dict[str, Any]:
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT *
                FROM events
                WHERE tenant_id = %s AND slug = %s
                LIMIT 1
                """,
                (tenant_id, slug),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="event_not_found")
    return _coerce_event_row(row)


def _load_sale_items(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    # In this codebase, sale_items are keyed by `tenant` (producer slug) + event_slug
    producer_slug = (
        event.get("tenant")
        or event.get("producer")
        or event.get("producer_slug")
        or event.get("owner")
    )
    if not producer_slug:
        return []

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT *
                FROM sale_items
                WHERE tenant = %s AND event_slug = %s
                ORDER BY COALESCE(sort_order, 999999), id
                """,
                (producer_slug, event.get("slug")),
            )
            rows = cur.fetchall() or []

    # Normalize output fields that the frontend usually needs
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        # Ensure numeric price is always present
        if "price" not in d and "price_cents" in d:
            d["price"] = d.get("price_cents")
        out.append(d)
    return out


@router.get("/config")
def public_config():
    return {"ok": True}


@router.get("/events")
def public_events_list(tenant: str = Query("default")):
    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT *
                FROM events
                WHERE tenant_id = %s
                ORDER BY COALESCE(date, '') ASC, COALESCE(created_at, 0) DESC
                """,
                (tenant,),
            )
            rows = cur.fetchall() or []

    events = [_coerce_event_row(r) for r in rows]
    return {"ok": True, "events": events}


@router.get("/events/{slug}")
def public_event_detail(slug: str, tenant: str = Query("default")):
    event = _load_event(tenant_id=tenant, slug=slug)
    sale_items = _load_sale_items(event)

    # Provide simple purchase-ready fields
    event["sale_items"] = sale_items
    if sale_items:
        prices = [
            (si.get("price") or si.get("price_cents") or 0)
            for si in sale_items
            if (si.get("price") is not None or si.get("price_cents") is not None)
        ]
        if prices:
            event["min_price"] = min(prices)

    return {"ok": True, "event": event}


@router.get("/sale-items")
def public_sale_items(
    tenant: str = Query("default"),
    event_slug: str = Query(..., description="Event slug"),
):
    event = _load_event(tenant_id=tenant, slug=event_slug)
    return {"ok": True, "sale_items": _load_sale_items(event)}
