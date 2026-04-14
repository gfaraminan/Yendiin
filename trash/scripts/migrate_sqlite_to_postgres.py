
import os
import sqlite3
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import execute_values

SQLITE_PATH = os.getenv("SQLITE_PATH", "entradas.sqlite")
PG_DSN = os.getenv("DATABASE_URL")

TABLES = [
    "buyers",
    "producers",
    "events",
    "ticket_types",
    "ticket_type_tiers",
    "sale_items",
    "event_sellers",
    "orders",
    "issued_tickets",
    "redeem_points",
    "catalog_items",
    "consumption_orders",
    "consumption_order_items",
    "consumption_redeems",
    "mp_sellers",
]

def pg_columns_with_types(cur, table):
    cur.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s
        ORDER BY ordinal_position
    """, (table,))
    return {c: t for c, t in cur.fetchall()}

def sqlite_columns(cur, table):
    cur.execute(f"PRAGMA table_info({table})")
    return {r[1]: (r[2] or "").upper() for r in cur.fetchall()}

def sqlite_count(cur, table):
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return cur.fetchone()[0]

def to_bool(v):
    if v is None: return None
    if isinstance(v, bool): return v
    return bool(int(v))

def to_ts(v):
    if v is None: return None
    if isinstance(v, int):
        return datetime.fromtimestamp(v/1000 if v > 10_000_000_000 else v, tz=timezone.utc)
    return v

def fetch_sqlite(cur, table, cols):
    select = []
    for c in cols:
        if table == "orders" and c == "legacy_order_id":
            select.append("order_id AS legacy_order_id")
        else:
            select.append(c)
    cur.execute(f"SELECT {', '.join(select)} FROM {table}")
    return cur.fetchall()

def upsert(pg_cur, table, cols, rows):
    if not rows:
        print(f" - {table}: 0 rows (skip)")
        return

    if table == "orders" and "legacy_order_id" in cols:
        conflict = "(legacy_order_id)"
    else:
        conflict = ""

    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s"
    if conflict:
        updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "legacy_order_id")
        sql += f" ON CONFLICT {conflict} DO UPDATE SET {updates}"

    execute_values(pg_cur, sql, rows, page_size=500)
    print(f" - {table}: {len(rows)} rows upserted")

def main():
    if not os.path.exists(SQLITE_PATH):
        raise RuntimeError("SQLite no existe")

    sq = sqlite3.connect(SQLITE_PATH)
    sq_cur = sq.cursor()

    pg = psycopg2.connect(PG_DSN)
    pg_cur = pg.cursor()

    print("SQLite:", SQLITE_PATH)
    print("Migrating tables...")

    for table in TABLES:
        try:
            n = sqlite_count(sq_cur, table)
        except Exception:
            print(f" - {table}: no existe en SQLite (skip)")
            continue

        pg_types = pg_columns_with_types(pg_cur, table)
        sq_types = sqlite_columns(sq_cur, table)

        common = [c for c in sq_types if c in pg_types]

        if table == "orders" and "legacy_order_id" in pg_types and "order_id" in sq_types:
            if "legacy_order_id" not in common:
                common.append("legacy_order_id")
                print("   · orders: mapping SQLite.order_id -> PG.legacy_order_id")

        if table == "orders" and "id" in common and pg_types["id"] == "uuid":
            common.remove("id")

        rows = fetch_sqlite(sq_cur, table, common)
        fixed = []
        for r in rows:
            rr = list(r)
            for i, c in enumerate(common):
                if pg_types[c] == "boolean":
                    rr[i] = to_bool(rr[i])
                if "timestamp" in pg_types[c]:
                    rr[i] = to_ts(rr[i])
            fixed.append(tuple(rr))

        print(f" - {table}: sqlite has {n} rows, common_cols={len(common)}")
        upsert(pg_cur, table, common, fixed)

    pg.commit()
    print("DONE")

if __name__ == "__main__":
    main()
PY
