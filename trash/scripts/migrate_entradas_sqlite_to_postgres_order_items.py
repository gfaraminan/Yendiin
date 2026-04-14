#!/usr/bin/env python3
"""
Migración Entradas (SQLite) -> Postgres compartido (Barra)

✅ Qué hace
- Crea schema de dominio "tickets" (configurable) en Postgres.
- Migra catálogos:
  - ticket_types -> tickets.ticket_types (mapeo tolerante: genera slug, ARS, qty_total=capacity, qty_sold=sold)
  - ticket_type_tiers -> tickets.ticket_type_tiers (tolerante a columnas faltantes)
  - issued_tickets -> tickets.issued_tickets (tolerante)
- Migra identidad + compras unificadas:
  - buyers.google_sub -> public.users (auth_provider='google', auth_subject=google_sub)
  - orders (PAID por default) -> public.orders (kind='tickets')
  - Normaliza líneas -> public.order_items (sin parsear JSON para BI)

🧪 Uso (Render / local)
  export DATABASE_URL="postgresql://user:pass@host/db"
  python migrate_entradas_sqlite_to_postgres_order_items.py --sqlite /var/data/entradas.sqlite --only-paid 1

Opciones:
  --schema tickets         schema destino para tablas de tickets (default: tickets)
  --only-paid 1|0          migrar solo PAID (default 1)
  --include-ticket-types 1|0   incluir ticket_types (default 1)
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# ----------------------------
# Postgres driver selection
# ----------------------------
_PG_MODE = "none"
try:
    import psycopg2  # type: ignore
    _PG_MODE = "psycopg2"
except Exception:
    psycopg2 = None  # type: ignore
    try:
        import psycopg  # type: ignore
        _PG_MODE = "psycopg"
    except Exception:
        psycopg = None  # type: ignore


def _pg_dsn() -> str:
    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or ""
    if not dsn:
        raise RuntimeError("Falta DATABASE_URL (Postgres).")
    return dsn


def _pg_connect():
    dsn = _pg_dsn()
    if _PG_MODE == "psycopg2":
        return psycopg2.connect(dsn)  # type: ignore
    if _PG_MODE == "psycopg":
        return psycopg.connect(dsn)  # type: ignore
    raise RuntimeError("No hay driver de Postgres instalado. Instalar psycopg2-binary o psycopg[binary].")


def _pg_exec(sql: str, params: Sequence[Any] = ()) -> None:
    conn = _pg_connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        cur.close()
    finally:
        conn.close()


def _pg_query(sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
    conn = _pg_connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        conn.commit()
        cur.close()
        return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()


_cols_cache: Dict[str, set] = {}


def _pg_cols(schema: str, table: str) -> set:
    key = f"{schema}.{table}"
    if key in _cols_cache:
        return _cols_cache[key]
    rows = _pg_query(
        "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s",
        (schema, table),
    )
    cols = {r["column_name"] for r in rows}
    _cols_cache[key] = cols
    return cols


def _pg_upsert_flexible(schema: str, table: str, row: Dict[str, Any], conflict_cols: Sequence[str]) -> None:
    """Upsert usando solo columnas que existan en destino."""
    cols = _pg_cols(schema, table)
    fields = [k for k in row.keys() if k in cols]
    if not fields:
        return

    # Asegurar columnas de conflicto si existen
    for c in conflict_cols:
        if c in cols and c in row and c not in fields:
            fields.append(c)

    insert_cols = ", ".join([f'"{c}"' for c in fields])
    placeholders = ", ".join(["%s"] * len(fields))
    non_conf = [c for c in fields if c not in set(conflict_cols)]
    if non_conf:
        set_clause = ", ".join([f'"{c}"=EXCLUDED."{c}"' for c in non_conf])
        on_conflict = f'ON CONFLICT ({", ".join([f\'"{c}"\' for c in conflict_cols])}) DO UPDATE SET {set_clause}'
    else:
        on_conflict = f'ON CONFLICT ({", ".join([f\'"{c}"\' for c in conflict_cols])}) DO NOTHING'

    sql = f'INSERT INTO "{schema}"."{table}" ({insert_cols}) VALUES ({placeholders}) {on_conflict}'
    _pg_exec(sql, [row.get(c) for c in fields])


# ----------------------------
# SQLite helpers
# ----------------------------
def row_has(r: sqlite3.Row, col: str) -> bool:
    return col in r.keys()


def row_get(r: sqlite3.Row, col: str, default: Any = None) -> Any:
    return r[col] if row_has(r, col) else default


def sqlite_table_exists(conn: sqlite3.Connection, name: str) -> bool:
    x = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone()
    return bool(x)


# ----------------------------
# Schema creation (Postgres)
# ----------------------------
def ensure_schema(schema: str) -> None:
    _pg_exec(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    # ticket_types: superset compatible con tu sqlite + campos "clásicos" para BI
    _pg_exec(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".ticket_types(
            id INTEGER PRIMARY KEY,
            tenant TEXT NOT NULL,
            event_slug TEXT,
            slug TEXT,
            name TEXT,
            description TEXT,
            price_cents INTEGER,
            currency TEXT,
            qty_total INTEGER,
            qty_sold INTEGER,
            active INTEGER,
            sort_order INTEGER,
            capacity INTEGER,
            sold INTEGER,
            sale_start BIGINT,
            sale_end BIGINT,
            created_at BIGINT,
            updated_at BIGINT
        );
        """
    )

    _pg_exec(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".ticket_type_tiers(
            id INTEGER PRIMARY KEY,
            tenant TEXT,
            ticket_type_id INTEGER,
            tier_name TEXT,
            price_cents INTEGER,
            qty_total INTEGER,
            qty_sold INTEGER,
            active INTEGER,
            created_at BIGINT,
            updated_at BIGINT
        );
        """
    )

    _pg_exec(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".issued_tickets(
            id INTEGER PRIMARY KEY,
            tenant TEXT,
            order_id TEXT,
            ticket_type_id INTEGER,
            buyer_sub TEXT,
            qr_token TEXT,
            status TEXT,
            issued_at BIGINT,
            redeemed_at BIGINT
        );
        """
    )

    # order_items en public
    _pg_exec(
        """
        CREATE TABLE IF NOT EXISTS public.order_items(
            id BIGSERIAL PRIMARY KEY,
            order_id TEXT NOT NULL,
            line_no INTEGER NOT NULL,
            sku TEXT,
            name TEXT,
            qty NUMERIC NOT NULL DEFAULT 0,
            unit_amount NUMERIC,
            total_amount NUMERIC,
            kind TEXT,
            meta JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(order_id, line_no)
        );
        """
    )


# ----------------------------
# Upserts: users + orders + order_items
# ----------------------------
def upsert_user_google(sub: str, email: Optional[str], name: Optional[str]) -> None:
    cols = _pg_cols("public", "users")
    if not {"auth_provider", "auth_subject"}.issubset(cols):
        raise RuntimeError("public.users no tiene (auth_provider, auth_subject). Revisar esquema de Barra.")

    now = int(time.time())
    payload = {
        "auth_provider": "google",
        "auth_subject": sub,
        "email": email,
        "name": name,
        "updated_at": now,
    }
    # created_at solo si existe
    if "created_at" in cols:
        payload["created_at"] = now

    _pg_upsert_flexible("public", "users", payload, conflict_cols=("auth_provider", "auth_subject"))


def upsert_order(order_row: Dict[str, Any]) -> None:
    cols = _pg_cols("public", "orders")
    if "id" not in cols:
        raise RuntimeError("public.orders no tiene columna id.")
    _pg_upsert_flexible("public", "orders", order_row, conflict_cols=("id",))


def replace_order_items(order_id: str, items: List[Dict[str, Any]], kind: str = "tickets") -> None:
    _pg_exec('DELETE FROM public.order_items WHERE order_id=%s', (order_id,))
    line_no = 1
    for it in items:
        _pg_exec(
            """
            INSERT INTO public.order_items(order_id, line_no, sku, name, qty, unit_amount, total_amount, kind, meta)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
            ON CONFLICT (order_id, line_no) DO UPDATE SET
              sku=EXCLUDED.sku,
              name=EXCLUDED.name,
              qty=EXCLUDED.qty,
              unit_amount=EXCLUDED.unit_amount,
              total_amount=EXCLUDED.total_amount,
              kind=EXCLUDED.kind,
              meta=EXCLUDED.meta
            """,
            (
                order_id,
                line_no,
                it.get("sku"),
                it.get("name"),
                it.get("qty", 0),
                it.get("unit_amount"),
                it.get("total_amount"),
                kind,
                json.dumps(it.get("meta") or {}, ensure_ascii=False),
            ),
        )
        line_no += 1


# ----------------------------
# Migration logic
# ----------------------------
def migrate_ticket_types(s: sqlite3.Connection, schema: str) -> None:
    if not sqlite_table_exists(s, "ticket_types"):
        print("INFO: SQLite sin ticket_types, se omite.")
        return

    tts = s.execute("SELECT * FROM ticket_types").fetchall()
    for r in tts:
        tt_id = row_get(r, "id")
        tenant = row_get(r, "tenant")
        event_slug = row_get(r, "event_slug")
        name = row_get(r, "name")
        price_cents = row_get(r, "price_cents", 0)
        active = row_get(r, "active", 1)
        sort_order = row_get(r, "sort_order", 0)
        capacity = row_get(r, "capacity", 0)
        sold = row_get(r, "sold", 0)

        slug = f"{event_slug}:tt:{tt_id}"
        row = {
            "id": tt_id,
            "tenant": tenant,
            "event_slug": event_slug,
            "slug": slug,
            "name": name,
            "description": "",          # no existe en tu sqlite
            "price_cents": price_cents,
            "currency": "ARS",          # default
            "qty_total": capacity,      # mapeo para modelo "clásico"
            "qty_sold": sold,           # mapeo para modelo "clásico"
            "active": active,
            "sort_order": sort_order,
            "capacity": capacity,
            "sold": sold,
            "sale_start": None,
            "sale_end": None,
            "created_at": None,
            "updated_at": None,
        }
        _pg_upsert_flexible(schema, "ticket_types", row, conflict_cols=("id",))


def migrate_ticket_type_tiers(s: sqlite3.Connection, schema: str) -> None:
    if not sqlite_table_exists(s, "ticket_type_tiers"):
        print("INFO: SQLite sin ticket_type_tiers, se omite.")
        return

    tiers = s.execute("SELECT * FROM ticket_type_tiers").fetchall()
    for r in tiers:
        row = {
            "id": row_get(r, "id"),
            "tenant": row_get(r, "tenant"),
            "ticket_type_id": row_get(r, "ticket_type_id"),
            "tier_name": row_get(r, "tier_name"),
            "price_cents": row_get(r, "price_cents"),
            "qty_total": row_get(r, "qty_total"),
            "qty_sold": row_get(r, "qty_sold"),
            "active": row_get(r, "active"),
            "created_at": row_get(r, "created_at"),
            "updated_at": row_get(r, "updated_at"),
        }
        _pg_upsert_flexible(schema, "ticket_type_tiers", row, conflict_cols=("id",))


def migrate_issued_tickets(s: sqlite3.Connection, schema: str) -> None:
    if not sqlite_table_exists(s, "issued_tickets"):
        print("INFO: SQLite sin issued_tickets, se omite.")
        return

    rows = s.execute("SELECT * FROM issued_tickets").fetchall()
    for r in rows:
        row = {
            "id": row_get(r, "id"),
            "tenant": row_get(r, "tenant"),
            "order_id": row_get(r, "order_id"),
            "ticket_type_id": row_get(r, "ticket_type_id"),
            "buyer_sub": row_get(r, "buyer_sub", row_get(r, "google_sub")),
            "qr_token": row_get(r, "qr_token"),
            "status": row_get(r, "status"),
            "issued_at": row_get(r, "issued_at"),
            "redeemed_at": row_get(r, "redeemed_at"),
        }
        _pg_upsert_flexible(schema, "issued_tickets", row, conflict_cols=("id",))


def migrate_buyers_to_users(s: sqlite3.Connection) -> None:
    if not sqlite_table_exists(s, "buyers"):
        print("INFO: SQLite sin buyers, se omite users.")
        return

    buyers = s.execute("SELECT * FROM buyers").fetchall()
    n = 0
    for b in buyers:
        sub = row_get(b, "google_sub")
        if not sub:
            continue
        upsert_user_google(
            sub=sub,
            email=row_get(b, "email"),
            name=row_get(b, "name"),
        )
        n += 1
    print(f"OK: users upserted desde buyers: {n}")


def migrate_orders_and_items(s: sqlite3.Connection, only_paid: bool) -> None:
    if not sqlite_table_exists(s, "orders"):
        raise RuntimeError("SQLite sin tabla orders. No hay nada para migrar.")

    q = "SELECT * FROM orders WHERE status='PAID'" if only_paid else "SELECT * FROM orders"
    orders = s.execute(q).fetchall()
    print(f"INFO: orders a migrar: {len(orders)} (only_paid={only_paid})")

    # cache simple de buyers por id
    buyers_by_id: Dict[int, sqlite3.Row] = {}
    if sqlite_table_exists(s, "buyers"):
        for b in s.execute("SELECT * FROM buyers").fetchall():
            bid = row_get(b, "id")
            if bid is not None:
                buyers_by_id[int(bid)] = b

    # cache ticket_types por id (para nombre/precio)
    tt_by_id: Dict[int, sqlite3.Row] = {}
    if sqlite_table_exists(s, "ticket_types"):
        for tt in s.execute("SELECT * FROM ticket_types").fetchall():
            tid = row_get(tt, "id")
            if tid is not None:
                tt_by_id[int(tid)] = tt

    migrated = 0
    for o in orders:
        # Id estable en Entradas puede ser order_id (string). Si no existe, usamos id.
        order_id = row_get(o, "order_id", str(row_get(o, "id")))
        status = row_get(o, "status")

        buyer_sub = None
        if row_has(o, "buyer_id") and row_get(o, "buyer_id") is not None:
            b = buyers_by_id.get(int(row_get(o, "buyer_id")))
            if b is not None:
                buyer_sub = row_get(b, "google_sub")

        # datos de ticket type si hay relación directa
        tt_name = None
        tt_id = row_get(o, "ticket_type_id")
        if tt_id is not None and int(tt_id) in tt_by_id:
            tt = tt_by_id[int(tt_id)]
            tt_name = row_get(tt, "name")

        qty = int(row_get(o, "qty", 1) or 1)
        # unit y total pueden variar según tu versión
        unit_cents = row_get(o, "unit_price_cents")
        if unit_cents is None and tt_id is not None and int(tt_id) in tt_by_id:
            unit_cents = row_get(tt_by_id[int(tt_id)], "price_cents", 0)
        unit_cents = int(unit_cents or 0)

        total_cents = row_get(o, "total_cents")
        total_cents = int(total_cents or (qty * unit_cents))

        unit_amount = round(unit_cents / 100.0, 2)
        total_amount = round(total_cents / 100.0, 2)

        item = {
            "sku": f"ticket:{tt_id}" if tt_id is not None else "ticket",
            "name": f"Entrada · {tt_name}" if tt_name else "Entrada",
            "qty": qty,
            "unit_amount": unit_amount,
            "total_amount": total_amount,
            "meta": {
                "ticket_type_id": tt_id,
                "ticket_type_name": tt_name,
                "unit_price_cents": unit_cents,
                "total_cents": total_cents,
            },
        }

        now = int(time.time())
        order_row = {
            "id": order_id,
            "kind": "tickets",
            "status": status,
            "currency": "ARS",
            "total_cents": total_cents,
            "total_amount": total_amount,
            "items_json": json.dumps([item], ensure_ascii=False),
            "auth_provider": "google" if buyer_sub else None,
            "auth_subject": buyer_sub,
            "source": "tickets-service",
            "updated_at": now,
        }
        # campos opcionales según tu tabla orders en Postgres
        if row_has(o, "event_slug"):
            order_row["event_slug"] = row_get(o, "event_slug")
        if row_has(o, "qr_token"):
            order_row["qr_token"] = row_get(o, "qr_token")
        if row_has(o, "payment_method"):
            order_row["payment_method"] = row_get(o, "payment_method")
        if row_has(o, "created_at"):
            order_row["created_at"] = row_get(o, "created_at") or now
        if row_has(o, "paid_at") and status == "PAID":
            order_row["paid_at"] = row_get(o, "paid_at")

        upsert_order(order_row)
        replace_order_items(order_id, [item], kind="tickets")
        migrated += 1

    print(f"OK: orders migradas: {migrated}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", required=True, help="Path al SQLite de Entradas (ej: /var/data/entradas.sqlite)")
    ap.add_argument("--schema", default="tickets", help="Schema destino tickets (default: tickets)")
    ap.add_argument("--only-paid", default="1", help="1 para migrar solo PAID (default 1)")
    ap.add_argument("--include-ticket-types", default="1", help="1 para migrar ticket_types (default 1)")
    args = ap.parse_args()

    only_paid = str(args.only_paid).strip().lower() in ("1", "true", "yes", "y")
    include_tt = str(args.include_ticket_types).strip().lower() in ("1", "true", "yes", "y")

    ensure_schema(args.schema)

    s = sqlite3.connect(args.sqlite)
    s.row_factory = sqlite3.Row

    # Catálogos / dominio
    if include_tt:
        migrate_ticket_types(s, args.schema)
    else:
        print("INFO: ticket_types omitido por flag --include-ticket-types 0")

    migrate_ticket_type_tiers(s, args.schema)
    migrate_issued_tickets(s, args.schema)

    # Core unificado
    migrate_buyers_to_users(s)
    migrate_orders_and_items(s, only_paid=only_paid)

    s.close()
    print("✅ OK | Migración finalizada")


if __name__ == "__main__":
    main()
