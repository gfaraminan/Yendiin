from __future__ import annotations

from typing import Dict, Any, Optional, List
from app.db import fetchone, fetchall, execute
import uuid

# Internal helpers (keep service layer consistent)

def _fetch_one(conn, sql: str, params: tuple = ()):
    return fetchone(conn, sql, params)

def _fetch_all(conn, sql: str, params: tuple = ()):
    return fetchall(conn, sql, params)

def list_events(conn, tenant_id: str | None):
    """
    List public events.
    If tenant_id is falsy or '*', returns all tenants (useful for demo).
    """
    if tenant_id and tenant_id != "*":
        sql = """
            SELECT
              tenant_id,
              slug,
              title,
              category,
              date_text,
              venue,
              city,
              flyer_url,
              hero_bg,
              badge
            FROM events
            WHERE active = true
              AND tenant_id = %s
            ORDER BY created_at DESC
        """
        return _fetch_all(conn, sql, (tenant_id,))
    sql = """
        SELECT
          tenant_id,
          slug,
          title,
          category,
          date_text,
          venue,
          city,
          flyer_url,
          hero_bg,
          badge
        FROM events
        WHERE active = true
        ORDER BY created_at DESC
    """
    return _fetch_all(conn, sql, ())

def get_event(conn, tenant_id: str | None, event_slug: str):
    """
    Fetch a single event. If tenant_id is provided, it is used.
    If not provided, fall back to the first active event with that slug (demo-friendly).
    """
    if tenant_id:
        sql = """
            SELECT
              tenant_id,
              slug,
              title,
              category,
              date_text,
              venue,
              city,
              flyer_url,
              hero_bg,
              badge,
              address,
              lat,
              lng,
              starts_at,
              ends_at
            FROM events
            WHERE active = true
              AND tenant_id = %s
              AND slug = %s
            LIMIT 1
        """
        row = _fetch_one(conn, sql, (tenant_id, event_slug))
        if row:
            return row

    sql2 = """
        SELECT
          tenant_id,
          slug,
          title,
          category,
          date_text,
          venue,
          city,
          flyer_url,
          hero_bg,
          badge,
          address,
          lat,
          lng,
          starts_at,
          ends_at
        FROM events
        WHERE active = true
          AND slug = %s
        ORDER BY created_at DESC
        LIMIT 1
    """
    return _fetch_one(conn, sql2, (event_slug,))


def list_event_sale_items(conn, tenant_id: str | None, event_slug: str):
    """List sale items for an event (PG-only). Tries 'sale_items' table; if missing, returns []."""
    if not tenant_id:
        # try resolve from event (demo-friendly)
        ev = get_event(conn, None, event_slug)
        tenant_id = ev["tenant_id"] if ev else None
    if not tenant_id:
        return []

    sql = """
        SELECT
          id,
          tenant,
          event_slug,
          name,
          kind,
          price_cents,
          stock_total,
          stock_sold,
          start_date,
          end_date,
          active,
          sort_order,
          created_at,
          updated_at
        FROM sale_items
        WHERE tenant = %s
          AND event_slug = %s
          AND active = true
        ORDER BY sort_order ASC, id ASC
    """
    try:
        return _fetch_all(conn, sql, (tenant_id, event_slug))
    except Exception as e:
        # Most common: undefined table/column during migration
        # psycopg specific error class
        if hasattr(e, "pgcode") or e.__class__.__name__.lower().find("undefined") >= 0:
            return []
        raise

def list_event_ticket_types(conn, tenant_id: str | None, event_slug: str):
    """Alias: ticket types = sale items of kind ticket/entrada."""
    items = list_event_sale_items(conn, tenant_id, event_slug)
    return [it for it in items if (it.get("kind") in ("ticket", "entrada"))]
