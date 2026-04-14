#!/usr/bin/env python3
"""
Migrate/Upsert events from SQLite -> Postgres (public.events).

Usage:
  python scripts/migrate_events_sqlite_to_pg.py --sqlite /var/data/entradas.sqlite

Env:
  DATABASE_URL=postgresql://...
"""

from __future__ import annotations
import os
import argparse
import sqlite3
import json
from typing import Any, Dict, List, Tuple, Optional

try:
    import psycopg2
    import psycopg2.extras
except Exception as e:
    raise SystemExit("Missing dependency psycopg2. Add 'psycopg2-binary' to requirements.txt") from e


PG_EVENTS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS public.events (
  slug text PRIMARY KEY
);

ALTER TABLE public.events ADD COLUMN IF NOT EXISTS tenant text;
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS title text;
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS category text;
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS date_text text;
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS venue text;
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS city text;
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS flyer_url text;
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS address text;
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS lat double precision;
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS lng double precision;
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS hero_bg text;
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS badge text;
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS active boolean DEFAULT true;
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS producer_id text;
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now();
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS updated_at timestamptz DEFAULT now();
"""


def pg_conn():
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("DATABASE_URL is not set.")
    return psycopg2.connect(dsn, sslmode="require")


def sqlite_conn(path: str):
    if not os.path.exists(path):
        raise SystemExit(f"SQLite file not found: {path}")
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def sqlite_table_columns(con: sqlite3.Connection, table: str) -> List[str]:
    cur = con.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    return cols


def pick(row: sqlite3.Row, cols: List[str], *candidates: str, default=None):
    for c in candidates:
        if c in cols:
            v = row[c]
            if v is not None:
                return v
    return default


def to_bool(v: Any, default: bool = True) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    try:
        if isinstance(v, (int, float)):
            return bool(v)
        s = str(v).strip().lower()
        if s in ("1", "true", "t", "yes", "y", "on", "active"):
            return True
        if s in ("0", "false", "f", "no", "n", "off", "inactive"):
            return False
    except Exception:
        pass
    return default


def to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def norm_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def migrate(sqlite_path: str, table: str = "events", limit: int = 0):
    # SQLite side
    scon = sqlite_conn(sqlite_path)
    cols = sqlite_table_columns(scon, table)
    if not cols:
        raise SystemExit(f"Could not read columns for SQLite table '{table}'. Does it exist?")

    q = f"SELECT * FROM {table}"
    if limit and limit > 0:
        q += f" LIMIT {int(limit)}"

    rows = scon.execute(q).fetchall()
    if not rows:
        print("No rows found in SQLite events table.")
        return

    # Postgres side
    pcon = pg_conn()
    pcon.autocommit = False
    try:
        with pcon.cursor() as cur:
            cur.execute(PG_EVENTS_SCHEMA_SQL)

        upsert_sql = """
        INSERT INTO public.events
        (slug, tenant, title, category, date_text, venue, city, flyer_url, address, lat, lng, hero_bg, badge, active, producer_id, updated_at)
        VALUES
        (%(slug)s, %(tenant)s, %(title)s, %(category)s, %(date_text)s, %(venue)s, %(city)s, %(flyer_url)s, %(address)s, %(lat)s, %(lng)s, %(hero_bg)s, %(badge)s, %(active)s, %(producer_id)s, now())
        ON CONFLICT (slug) DO UPDATE SET
          tenant = COALESCE(EXCLUDED.tenant, public.events.tenant),
          title = COALESCE(EXCLUDED.title, public.events.title),
          category = COALESCE(EXCLUDED.category, public.events.category),
          date_text = COALESCE(EXCLUDED.date_text, public.events.date_text),
          venue = COALESCE(EXCLUDED.venue, public.events.venue),
          city = COALESCE(EXCLUDED.city, public.events.city),
          flyer_url = COALESCE(EXCLUDED.flyer_url, public.events.flyer_url),
          address = COALESCE(EXCLUDED.address, public.events.address),
          lat = COALESCE(EXCLUDED.lat, public.events.lat),
          lng = COALESCE(EXCLUDED.lng, public.events.lng),
          hero_bg = COALESCE(EXCLUDED.hero_bg, public.events.hero_bg),
          badge = COALESCE(EXCLUDED.badge, public.events.badge),
          active = COALESCE(EXCLUDED.active, public.events.active),
          producer_id = COALESCE(EXCLUDED.producer_id, public.events.producer_id),
          updated_at = now();
        """

        n_ok = 0
        n_skip = 0

        with pcon.cursor() as cur:
            for r in rows:
                slug = norm_str(pick(r, cols, "slug", "event_slug", "code", "id"))
                if not slug:
                    n_skip += 1
                    continue

                payload = {
                    "slug": slug,
                    "tenant": norm_str(pick(r, cols, "tenant", "org", "account", "event_tenant")),
                    "title": norm_str(pick(r, cols, "title", "name", "event_name")),
                    "category": norm_str(pick(r, cols, "category", "type")),
                    "date_text": norm_str(pick(r, cols, "date_text", "date", "starts_at", "start_time", "datetime")),
                    "venue": norm_str(pick(r, cols, "venue", "venue_name", "place", "location", "local")),
                    "city": norm_str(pick(r, cols, "city", "town")),
                    "flyer_url": norm_str(pick(r, cols, "flyer_url", "banner_url", "image_url", "poster_url")),
                    "address": norm_str(pick(r, cols, "address", "addr", "street")),
                    "lat": to_float(pick(r, cols, "lat", "latitude")),
                    "lng": to_float(pick(r, cols, "lng", "lon", "longitude")),
                    "hero_bg": norm_str(pick(r, cols, "hero_bg", "hero", "bg")),
                    "badge": norm_str(pick(r, cols, "badge")),
                    "active": to_bool(pick(r, cols, "active", "is_active", "enabled"), default=True),
                    "producer_id": norm_str(pick(r, cols, "producer_id", "owner_slug", "producer_slug")),
                }

                cur.execute(upsert_sql, payload)
                n_ok += 1

        pcon.commit()
        print(f"OK: events upserted: {n_ok} | skipped (no slug): {n_skip}")

    except Exception:
        pcon.rollback()
        raise
    finally:
        try:
            pcon.close()
        except Exception:
            pass
        try:
            scon.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", required=True, help="Path to entradas.sqlite (e.g. /var/data/entradas.sqlite)")
    ap.add_argument("--table", default="events", help="SQLite table name (default: events)")
    ap.add_argument("--limit", type=int, default=0, help="Limit rows (0 = all)")
    args = ap.parse_args()
    migrate(args.sqlite, table=args.table, limit=args.limit)


if __name__ == "__main__":
    main()
