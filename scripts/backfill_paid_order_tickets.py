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
    add("buyer_phone", _first_non_empty(order.get("buyer_phone"), item.get("buyer_phone"), item.get("phone")) or None)
    add("buyer_dni", _first_non_empty(order.get("buyer_dni"), item.get("buyer_dni"), item.get("document_number"), item.get("dni")) or None)
    add("buyer_address", _first_non_empty(order.get("buyer_address"), item.get("buyer_address"), item.get("address")) or None)
    add("buyer_province", _first_non_empty(order.get("buyer_province"), item.get("buyer_province"), item.get("province")) or None)
    add(
        "buyer_postal_code",
        _first_non_empty(order.get("buyer_postal_code"), item.get("buyer_postal_code"), item.get("postal_code"), item.get("zip_code")) or None,
    )
    add("buyer_birth_date", _first_non_empty(order.get("buyer_birth_date"), item.get("buyer_birth_date"), item.get("birth_date")) or None)

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

            where = ["lower(COALESCE(o.status, '')) = 'paid"]
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
