from __future__ import annotations

from typing import Optional, Dict, Any, List
from app.db import fetchall, fetchone, execute

def list_sellers(conn, tenant: str, event_slug: str) -> List[Dict[str, Any]]:
    rows = fetchall(conn, """
        SELECT code, name, active, created_at
        FROM public.event_sellers
        WHERE tenant=%s AND event_slug=%s
        ORDER BY active DESC, code ASC
    """, (tenant, event_slug))
    return [dict(r) for r in rows]

def upsert_seller(conn, tenant: str, event_slug: str, code: str, name: str, active: bool=True) -> Dict[str, Any]:
    # Key logical: (tenant, event_slug, code)
    execute(conn, """
        INSERT INTO public.event_sellers(tenant, event_slug, code, name, active, created_at)
        VALUES(%s,%s,%s,%s,%s, extract(epoch from now())::bigint)
        ON CONFLICT (tenant, event_slug, code)
        DO UPDATE SET name=EXCLUDED.name, active=EXCLUDED.active
    """, (tenant, event_slug, code, name, bool(active)))
    row = fetchone(conn, """
        SELECT code, name, active, created_at
        FROM public.event_sellers
        WHERE tenant=%s AND event_slug=%s AND code=%s
    """, (tenant, event_slug, code))
    return dict(row) if row else {"code": code, "name": name, "active": bool(active)}

def list_sale_items(conn, tenant: str, event_slug: str) -> List[Dict[str, Any]]:
    rows = fetchall(conn, """
        SELECT id, name, kind, price_cents, stock_total, stock_sold, start_date, end_date, active, sort_order, created_at, updated_at
        FROM public.sale_items
        WHERE tenant=%s AND event_slug=%s
        ORDER BY COALESCE(sort_order,0), id DESC
    """, (tenant, event_slug))
    return [dict(r) for r in rows]

def upsert_sale_item(conn,
    tenant: str,
    event_slug: str,
    kind: str,
    name: str,
    price_cents: int,
    stock_total: Optional[int],
    start_date: Optional[str],
    end_date: Optional[str],
    active: bool,
    sort_order: int
) -> Dict[str, Any]:
    # Key logical: (tenant, event_slug, kind, name)
    execute(conn, """
        INSERT INTO public.sale_items(
            tenant, event_slug, name, kind, price_cents, stock_total, stock_sold,
            start_date, end_date, active, sort_order, created_at, updated_at
        )
        VALUES(
            %s,%s,%s,%s,%s,%s,0,
            %s,
            %s,
            %s,%s,extract(epoch from now())::bigint,extract(epoch from now())::bigint
        )
        ON CONFLICT (tenant, event_slug, kind, name)
        DO UPDATE SET
            price_cents=EXCLUDED.price_cents,
            stock_total=EXCLUDED.stock_total,
            start_date=EXCLUDED.start_date,
            end_date=EXCLUDED.end_date,
            active=EXCLUDED.active,
            sort_order=EXCLUDED.sort_order,
            updated_at=extract(epoch from now())::bigint
    """, (
        tenant, event_slug, name, kind, int(price_cents), stock_total,
        start_date,
        end_date,
        bool(active), int(sort_order or 0)
    ))
    row = fetchone(conn, """
        SELECT id, name, kind, price_cents, stock_total, stock_sold, start_date, end_date, active, sort_order
        FROM public.sale_items
        WHERE tenant=%s AND event_slug=%s AND kind=%s AND name=%s
    """, (tenant, event_slug, kind, name))
    return dict(row) if row else {"name": name, "kind": kind}
