#!/usr/bin/env python3
"""Backfill persisted tickets for paid orders that only have orders.items_json.

Usage examples:
  DATABASE_URL=... python scripts/backfill_paid_order_tickets.py --event-slug 3er-prueba-creador-completo
  DATABASE_URL=... python scripts/backfill_paid_order_tickets.py --event-slug 3er-prueba-creador-completo --execute
  DATABASE_URL=... python scripts/backfill_paid_order_tickets.py --tenant-id default --execute

The script is dry-run by default. It is idempotent at the order level: orders
that already have at least one persisted ticket are skipped.
"""
from __future__ import annotations

import argparse
import json
import os
import uuid
from typing import Any

import psycopg
from psycopg.rows import dict_row


def _table_columns(cur, table: str) -> set[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table,),
    )
    return {str(r["column_name"]) for r in cur.fetchall() or [] if r.get("column_name")}


def _normalize_items(items_raw: Any) -> list[dict[str, Any]]:
    data = items_raw
    if isinstance(items_raw, str):
        try:
            data = json.loads(items_raw)
        except Exception:
            return []
    if isinstance(data, dict):
        data = data.get("items") if isinstance(data.get("items"), list) else [data]
    if not isinstance(data, list):
        return []
    return [it for it in data if isinstance(it, dict)]


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _buyer_values(order: dict[str, Any], item: dict[str, Any]) -> dict[str, str]:
    return {
        "buyer_name": _first_non_empty(order.get("buyer_name"), item.get("buyer_name"), item.get("full_name"), item.get("fullName"), item.get("buyer_full_name")),
        "buyer_email": _first_non_empty(order.get("buyer_email"), item.get("buyer_email"), item.get("email"), item.get("mail")),
        "buyer_phone": _first_non_empty(order.get("buyer_phone"), item.get("buyer_phone"), item.get("phone")),
        "buyer_dni": _first_non_empty(order.get("buyer_dni"), item.get("buyer_dni"), item.get("document_number"), item.get("dni")),
        "buyer_address": _first_non_empty(order.get("buyer_address"), item.get("buyer_address"), item.get("address")),
        "buyer_province": _first_non_empty(order.get("buyer_province"), item.get("buyer_province"), item.get("province")),
        "buyer_postal_code": _first_non_empty(order.get("buyer_postal_code"), item.get("buyer_postal_code"), item.get("postal_code"), item.get("zip_code")),
        "buyer_birth_date": _first_non_empty(order.get("buyer_birth_date"), item.get("buyer_birth_date"), item.get("birth_date")),
    }


def _hydrate_existing_tickets(cur, *, ocols: set[str], tcols: set[str], tenant_id: str, event_slug: str, execute: bool, limit: int) -> tuple[int, int]:
    buyer_cols = [
        c for c in ("buyer_name", "buyer_email", "buyer_phone", "buyer_dni", "buyer_address", "buyer_province", "buyer_postal_code", "buyer_birth_date")
        if c in tcols
    ]
    if not buyer_cols:
        return (0, 0)

    where = ["t.order_id IS NOT NULL"]
    params: list[Any] = []
    if "tenant_id" in tcols and tenant_id:
        where.append("t.tenant_id = %s")
        params.append(tenant_id)
    if event_slug:
        where.append("t.event_slug = %s")
        params.append(event_slug)
    where.append("(" + " OR ".join([f"t.{c} IS NULL OR t.{c} = ''" for c in buyer_cols]) + ")")
    params.append(max(1, int(limit)))

    cur.execute(
        f"""
        SELECT t.id AS ticket_id, t.sale_item_id AS ticket_sale_item_id, o.*
        FROM tickets t
        JOIN orders o ON o.id::text = t.order_id::text
        WHERE {' AND '.join(where)}
        ORDER BY t.created_at DESC NULLS LAST, t.id DESC
        LIMIT %s
        """,
        tuple(params),
    )
    rows = cur.fetchall() or []
    updated = 0
    for row in rows:
        order = dict(row)
        items = _normalize_items(order.get("items_json"))
        sale_item_id = str(order.get("ticket_sale_item_id") or "").strip()
        item = next((it for it in items if str(it.get("sale_item_id") or it.get("id") or "").strip() == sale_item_id), items[0] if items else {})
        values = _buyer_values(order, item)
        assignments = []
        args: list[Any] = []
        for col in buyer_cols:
            value = values.get(col) or ""
            if value:
                assignments.append(f"{col} = COALESCE(NULLIF({col}, ''), %s)")
                args.append(value)
        if not assignments:
            continue
        updated += 1
        if execute:
            args.append(order.get("ticket_id"))
            cur.execute(f"UPDATE tickets SET {', '.join(assignments)} WHERE id = %s", tuple(args))
    return (len(rows), updated)


def _insert_ticket(cur, *, tcols: set[str], order: dict[str, Any], item: dict[str, Any], seq: int) -> None:
    sale_item_id = _first_non_empty(item.get("sale_item_id"), item.get("id"), "item")
    qr_value = uuid.uuid4().hex
    cols: list[str] = []
    vals: list[str] = []
    args: list[Any] = []

    def add(col: str, val: Any) -> None:
        if col in tcols:
            cols.append(col)
            vals.append("%s")
            args.append(val)

    add("id", str(uuid.uuid4()))
    add("order_id", str(order.get("id") or order.get("order_id") or ""))
    add("tenant_id", order.get("tenant_id") or "default")
    add("producer_tenant", order.get("producer_tenant"))
    add("event_slug", order.get("event_slug"))
    add("sale_item_id", sale_item_id)
    add("status", "issued")
    add("qr_token", qr_value)
    add("qr_payload", qr_value)
    buyer_values = _buyer_values(order, item)
    for col, value in buyer_values.items():
        add(col, value or None)

    if "created_at" in tcols:
        cols.append("created_at")
        vals.append("COALESCE(%s::timestamptz, NOW())")
        args.append(order.get("created_at"))

    required = {"id", "order_id", "event_slug", "status"}
    missing = required - set(cols)
    if missing:
        raise RuntimeError(f"tickets schema missing required columns: {sorted(missing)}")

    cur.execute(f"INSERT INTO tickets ({', '.join(cols)}) VALUES ({', '.join(vals)})", tuple(args))


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill tickets for paid orders without persisted tickets.")
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--event-slug", default="")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--execute", action="store_true", help="Actually insert tickets. Default is dry-run.")
    parser.add_argument(
        "--hydrate-existing",
        action="store_true",
        help="Update existing tickets with buyer fields from orders/items_json instead of inserting missing ticket rows.",
    )
    args = parser.parse_args()

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("Missing DATABASE_URL")

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            ocols = _table_columns(cur, "orders")
            tcols = _table_columns(cur, "tickets")
            if not {"id", "items_json", "status"}.issubset(ocols):
                raise SystemExit("orders schema must include id, items_json and status")
            if not ({"qr_token", "qr_payload"} & tcols):
                raise SystemExit("tickets schema must include qr_token or qr_payload before backfill")

            if args.hydrate_existing:
                scanned, updated = _hydrate_existing_tickets(
                    cur,
                    ocols=ocols,
                    tcols=tcols,
                    tenant_id=args.tenant_id,
                    event_slug=args.event_slug,
                    execute=args.execute,
                    limit=max(1, int(args.limit)),
                )
                if args.execute:
                    conn.commit()
                else:
                    conn.rollback()
                mode = "EXECUTE" if args.execute else "DRY-RUN"
                print(f"{mode} HYDRATE: scanned_tickets={scanned} updatable_tickets={updated}")
                return

            where = ["lower(COALESCE(o.status, '')) = 'paid'"]
            params: list[Any] = []
            if "tenant_id" in ocols and args.tenant_id:
                where.append("o.tenant_id = %s")
                params.append(args.tenant_id)
            if args.event_slug:
                where.append("o.event_slug = %s")
                params.append(args.event_slug)
            params.append(max(1, int(args.limit)))

            cur.execute(
                f"""
                SELECT o.*
                FROM orders o
                WHERE {' AND '.join(where)}
                  AND NOT EXISTS (
                    SELECT 1 FROM tickets t WHERE t.order_id::text = o.id::text
                  )
                ORDER BY o.created_at DESC NULLS LAST, o.id DESC
                LIMIT %s
                """,
                tuple(params),
            )
            orders = cur.fetchall() or []

            planned = 0
            inserted = 0
            for order in orders:
                items = _normalize_items(order.get("items_json"))
                order_count = 0
                for item in items:
                    try:
                        qty = int(item.get("qty") or item.get("quantity") or 1)
                    except Exception:
                        qty = 1
                    for seq in range(1, max(0, qty) + 1):
                        planned += 1
                        order_count += 1
                        if args.execute:
                            _insert_ticket(cur, tcols=tcols, order=order, item=item, seq=seq)
                            inserted += 1
                print(f"order={order.get('id')} event={order.get('event_slug')} planned_tickets={order_count}")

            if args.execute:
                conn.commit()
            else:
                conn.rollback()

    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"{mode}: orders={len(orders)} planned_tickets={planned} inserted={inserted}")


if __name__ == "__main__":
    main()
