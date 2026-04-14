# repos/events_repo.py
from __future__ import annotations

from typing import Any

from db.pg import fetchall, fetchone, pg_columns, pg_table_exists


DESIRED_EVENT_COLS = [
    "slug","title","category","date_text","venue","city","hero_bg","badge",
    "flyer_url","address","lat","lng","date_iso","active","tenant"
]


def _col_expr(cols: set[str], col: str) -> str:
    if col not in cols:
        # defaults compatibles con el front
        if col in ("lat", "lng"):
            return f"NULL AS {col}"
        return f"'' AS {col}"
    if col in ("lat", "lng"):
        return f"{col} AS {col}"
    return f"COALESCE({col},'') AS {col}"


def list_events_for_tenant(tenant: str) -> list[dict[str, Any]]:
    if not pg_table_exists("events"):
        return []

    cols = pg_columns("events")
    select_parts = [_col_expr(cols, c) for c in DESIRED_EVENT_COLS if c not in ("active","tenant")]
    sql = f"SELECT {', '.join(select_parts)} FROM public.events WHERE 1=1"
    params: list[Any] = []

    if "tenant" in cols:
        sql += " AND tenant=%s"
        params.append(tenant)

    if "active" in cols:
        sql += " AND COALESCE(active,true)=true"

    sql += " ORDER BY COALESCE(date_text,''), title"

    events = fetchall(sql, params)

    # min_price por evento (si existe ticket_types)
    if pg_table_exists("ticket_types"):
        tt_cols = pg_columns("ticket_types")
        has_tenant = "tenant" in tt_cols
        has_active = "active" in tt_cols
        has_price = "price_cents" in tt_cols
        has_event_slug = "event_slug" in tt_cols
        if has_price and has_event_slug:
            for ev in events:
                slug = (ev.get("slug") or "").strip()
                if not slug:
                    ev["min_price"] = None
                    continue
                ev["min_price"] = min_price_for_event(slug, tenant if has_tenant else None, has_active=has_active)

    # asegurar key aunque no exista ticket_types
    for ev in events:
        ev.setdefault("min_price", None)

    return events


def min_price_for_event(event_slug: str, tenant: str | None, has_active: bool = True) -> int | None:
    tt_cols = pg_columns("ticket_types")
    sql = "SELECT MIN(price_cents) AS min_price FROM public.ticket_types WHERE event_slug=%s"
    params: list[Any] = [event_slug]

    if tenant and "tenant" in tt_cols:
        sql += " AND tenant=%s"
        params.append(tenant)
    if has_active and "active" in tt_cols:
        sql += " AND COALESCE(active,true)=true"

    row = fetchone(sql, params)
    if not row:
        return None
    return row.get("min_price")


def get_event_meta(event_slug: str, tenant: str | None = None) -> dict[str, Any]:
    if not pg_table_exists("events"):
        return {
            "event_title": "", "event_date_text": "", "event_date_iso": "",
            "event_venue": "", "event_city": "", "event_hero": ""
        }

    cols = pg_columns("events")

    # armamos un SELECT solo con columnas existentes (sin inventar)
    def pick(col: str, alias: str) -> str:
        if col not in cols:
            return f"'' AS {alias}"
        return f"COALESCE({col},'') AS {alias}"

    select_parts = [
        pick("title", "event_title"),
        pick("date_text", "event_date_text"),
        pick("date_iso", "event_date_iso"),
        pick("venue", "event_venue"),
        pick("city", "event_city"),
        pick("hero_bg", "event_hero"),
    ]

    sql = f"SELECT {', '.join(select_parts)} FROM public.events WHERE slug=%s"
    params: list[Any] = [event_slug]

    if tenant and "tenant" in cols:
        sql += " AND tenant=%s"
        params.append(tenant)

    sql += " LIMIT 1"
    row = fetchone(sql, params)
    if not row:
        return {
            "event_title": "", "event_date_text": "", "event_date_iso": "",
            "event_venue": "", "event_city": "", "event_hero": ""
        }
    return row
