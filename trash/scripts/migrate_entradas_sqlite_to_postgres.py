"""Migrate Entradas (SQLite) -> Postgres shared DB (Barra).
- Upserts users (google) into public.users
- Mirrors paid orders into public.orders (flex insert by existing columns)
- Migrates ticket_types / ticket_type_tiers / issued_tickets into schema "tickets" (default)

Usage:
  export DATABASE_URL=...
  python migrate_entradas_sqlite_to_postgres.py --sqlite ./entradas.db

Optional:
  --only-paid 1   (default)
  --schema tickets
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import json
import time
from typing import Any, Dict, List, Tuple

try:
    import psycopg2  # type: ignore
    import psycopg2.extras  # type: ignore
    _PG_DRIVER = "psycopg2"
except Exception:
    psycopg2 = None  # type: ignore
    try:
        import psycopg  # type: ignore
        _PG_DRIVER = "psycopg"
    except Exception:
        psycopg = None  # type: ignore
        _PG_DRIVER = "none"


def _pg_dsn() -> str:
    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or ""
    if not dsn:
        raise RuntimeError("DATABASE_URL no está configurado.")
    return dsn


def _pg_connect():
    dsn = _pg_dsn()
    if _PG_DRIVER == "psycopg2":
        return psycopg2.connect(dsn)  # type: ignore
    if _PG_DRIVER == "psycopg":
        return psycopg.connect(dsn)  # type: ignore
    raise RuntimeError("No hay driver de Postgres instalado (psycopg2 o psycopg).")


def _pg_fetchall(sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
    conn = _pg_connect()
    try:
        if _PG_DRIVER == "psycopg2":
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)  # type: ignore
            cur.execute(sql, params)
            rows = cur.fetchall()
            conn.commit()
            cur.close()
            return [dict(r) for r in (rows or [])]
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        conn.commit()
        cur.close()
        return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()


def _pg_exec(sql: str, params: Tuple[Any, ...] = ()) -> None:
    conn = _pg_connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        cur.close()
    finally:
        conn.close()


_cols_cache: Dict[str, set] = {}


def _pg_cols(table: str, schema: str = "public") -> set:
    key = f"{schema}.{table}"
    if key in _cols_cache:
        return _cols_cache[key]
    rows = _pg_fetchall(
        "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s",
        (schema, table),
    )
    cols = {r["column_name"] for r in rows}
    _cols_cache[key] = cols
    return cols


def ensure_tickets_schema(schema: str) -> None:
    _pg_exec(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    _pg_exec(f'''
    CREATE TABLE IF NOT EXISTS "{schema}".ticket_types(
        id INTEGER PRIMARY KEY,
        tenant TEXT NOT NULL,
        slug TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        price_cents INTEGER NOT NULL,
        currency TEXT,
        qty_total INTEGER,
        qty_sold INTEGER,
        active INTEGER,
        sale_start INTEGER,
        sale_end INTEGER,
        created_at INTEGER,
        updated_at INTEGER,
        UNIQUE(tenant, slug)
    )
    ''')

    _pg_exec(f'''
    CREATE TABLE IF NOT EXISTS "{schema}".ticket_type_tiers(
        id INTEGER PRIMARY KEY,
        tenant TEXT NOT NULL,
        ticket_type_id INTEGER NOT NULL,
        tier_name TEXT NOT NULL,
        price_cents INTEGER NOT NULL,
        qty_total INTEGER,
        qty_sold INTEGER,
        active INTEGER,
        created_at INTEGER,
        updated_at INTEGER
    )
    ''')

    _pg_exec(f'''
    CREATE TABLE IF NOT EXISTS "{schema}".issued_tickets(
        id INTEGER PRIMARY KEY,
        tenant TEXT NOT NULL,
        order_id TEXT NOT NULL,
        ticket_type_id INTEGER NOT NULL,
        buyer_sub TEXT,
        qr_token TEXT NOT NULL,
        status TEXT,
        issued_at INTEGER,
        redeemed_at INTEGER
    )
    ''')


def upsert_user_google(sub: str, email: str, name: str) -> None:
    cols = _pg_cols("users")
    if not {"auth_provider", "auth_subject"}.issubset(cols):
        raise RuntimeError("public.users no tiene auth_provider/auth_subject. Barra no está en esquema esperado.")
    payload = {
        "auth_provider": "google",
        "auth_subject": sub,
        "email": email or None,
        "name": name or None,
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
    }
    fields = [k for k in payload if k in cols]
    insert_cols = ", ".join(fields)
    placeholders = ", ".join(["%s"] * len(fields))
    update_set = ", ".join([f"{k}=EXCLUDED.{k}" for k in fields if k not in ("auth_provider","auth_subject","created_at")])
    sql = f"""
    INSERT INTO users ({insert_cols})
    VALUES ({placeholders})
    ON CONFLICT (auth_provider, auth_subject)
    DO UPDATE SET {update_set}
    """
    _pg_exec(sql, tuple(payload[k] for k in fields))


def upsert_order_flexible(order: Dict[str, Any]) -> None:
    cols = _pg_cols("orders")
    if "id" not in cols:
        raise RuntimeError("public.orders no tiene 'id'.")
    fields = [k for k in order if k in cols]
    if "id" not in fields:
        fields.append("id")
    insert_cols = ", ".join(fields)
    placeholders = ", ".join(["%s"] * len(fields))
    update_fields = [k for k in fields if k not in ("id","created_at")]
    if update_fields:
        update_set = ", ".join([f"{k}=EXCLUDED.{k}" for k in update_fields])
        on_conflict = f"ON CONFLICT (id) DO UPDATE SET {update_set}"
    else:
        on_conflict = "ON CONFLICT (id) DO NOTHING"
    sql = f"INSERT INTO orders ({insert_cols}) VALUES ({placeholders}) {on_conflict}"
    _pg_exec(sql, tuple(order.get(k) for k in fields))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", required=True, help="Path al SQLite de Entradas")
    ap.add_argument("--schema", default="tickets", help="Schema destino para tablas de tickets")
    ap.add_argument("--only-paid", default="1", help="1 para migrar solo ordenes PAID (default)")
    args = ap.parse_args()

    only_paid = str(args.only_paid).strip().lower() in ("1","true","yes","y")

    ensure_tickets_schema(args.schema)

    s = sqlite3.connect(args.sqlite)
    s.row_factory = sqlite3.Row

    # ticket types
    tts = s.execute("SELECT * FROM ticket_types").fetchall()
    for r in tts:
        _pg_exec(
            f'''INSERT INTO "{args.schema}".ticket_types
            (id, tenant, slug, name, description, price_cents, currency, qty_total, qty_sold, active, sale_start, sale_end, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
              tenant=EXCLUDED.tenant, slug=EXCLUDED.slug, name=EXCLUDED.name, description=EXCLUDED.description,
              price_cents=EXCLUDED.price_cents, currency=EXCLUDED.currency, qty_total=EXCLUDED.qty_total, qty_sold=EXCLUDED.qty_sold,
              active=EXCLUDED.active, sale_start=EXCLUDED.sale_start, sale_end=EXCLUDED.sale_end, updated_at=EXCLUDED.updated_at
            ''',
            (
                r["id"], r["tenant"], r["slug"], r["name"], r["description"], r["price_cents"], r["currency"],
                r["qty_total"], r["qty_sold"], r["active"], r["sale_start"], r["sale_end"], r["created_at"], r["updated_at"]
            )
        )

    tiers = s.execute("SELECT * FROM ticket_type_tiers").fetchall()
    for r in tiers:
        _pg_exec(
            f'''INSERT INTO "{args.schema}".ticket_type_tiers
            (id, tenant, ticket_type_id, tier_name, price_cents, qty_total, qty_sold, active, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
              tenant=EXCLUDED.tenant, ticket_type_id=EXCLUDED.ticket_type_id, tier_name=EXCLUDED.tier_name,
              price_cents=EXCLUDED.price_cents, qty_total=EXCLUDED.qty_total, qty_sold=EXCLUDED.qty_sold,
              active=EXCLUDED.active, updated_at=EXCLUDED.updated_at
            ''',
            (
                r["id"], r["tenant"], r["ticket_type_id"], r["tier_name"], r["price_cents"],
                r["qty_total"], r["qty_sold"], r["active"], r["created_at"], r["updated_at"]
            )
        )

    # buyers -> users
    buyers = s.execute("SELECT * FROM buyers").fetchall()
    for b in buyers:
        if b["google_sub"]:
            upsert_user_google(b["google_sub"], b["email"] or "", b["name"] or "")

    # paid orders -> core orders
    if only_paid:
        orders = s.execute("SELECT * FROM orders WHERE status='PAID'").fetchall()
    else:
        orders = s.execute("SELECT * FROM orders").fetchall()

    for o in orders:
        b = s.execute("SELECT * FROM buyers WHERE id=?", (o["buyer_id"],)).fetchone()
        tt = s.execute("SELECT * FROM ticket_types WHERE id=?", (o["ticket_type_id"],)).fetchone()
        item = {
            "type": "ticket",
            "ticket_type_id": o["ticket_type_id"],
            "ticket_type_name": (tt["name"] if tt else None),
            "qty": int(o["qty"]),
            "unit_price_cents": int(o["unit_price_cents"]),
            "total_cents": int(o["total_cents"]),
        }
        order_doc = {
            "id": o["order_id"],
            "kind": "tickets",
            "event_slug": o["event_slug"],
            "status": o["status"],
            "currency": "ARS",
            "total_cents": int(o["total_cents"]),
            "total_amount": int(o["total_cents"] // 100),
            "items_json": json.dumps([item], ensure_ascii=False),
            "qr_token": o["qr_token"],
            "auth_provider": "google" if b and b["google_sub"] else None,
            "auth_subject": (b["google_sub"] if b else None),
            "created_at": int(o["created_at"] or time.time()),
            "updated_at": int(time.time()),
            "paid_at": int(o["paid_at"] or time.time()) if o["status"] == "PAID" else None,
            "payment_method": o["payment_method"],
            "source": "tickets-service",
        }
        upsert_order_flexible(order_doc)

    # issued tickets
    its = s.execute("SELECT * FROM issued_tickets").fetchall()
    for r in its:
        _pg_exec(
            f'''INSERT INTO "{args.schema}".issued_tickets
            (id, tenant, order_id, ticket_type_id, buyer_sub, qr_token, status, issued_at, redeemed_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
              tenant=EXCLUDED.tenant, order_id=EXCLUDED.order_id, ticket_type_id=EXCLUDED.ticket_type_id,
              buyer_sub=EXCLUDED.buyer_sub, qr_token=EXCLUDED.qr_token, status=EXCLUDED.status,
              issued_at=EXCLUDED.issued_at, redeemed_at=EXCLUDED.redeemed_at
            ''',
            (
                r["id"], r["tenant"], r["order_id"], r["ticket_type_id"], r["buyer_sub"], r["qr_token"],
                r["status"], r["issued_at"], r["redeemed_at"]
            )
        )

    s.close()
    print("OK | Migración finalizada")


if __name__ == "__main__":
    main()
