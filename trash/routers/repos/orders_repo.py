# repos/orders_repo.py
from __future__ import annotations

from typing import Any

from db.pg import fetchall, fetchone, pg_columns, pg_table_exists


def list_orders_for_subject_deduped(*, auth_provider: str, auth_subject: str, limit: int = 200) -> list[dict[str, Any]]:
    if not pg_table_exists("orders"):
        return []

    cols = pg_columns("orders")

    want = [
        "id","event_slug","created_at","status","total_amount","total_cents",
        "currency","qr_token","paid_at","items_json","mp_status","mp_payment_id",
        "pickup_code","sale_item_id","ticket_type_id"
    ]
    select_cols = [c for c in want if c in cols]
    if "id" not in select_cols:
        select_cols.insert(0, "id")

    # Dedupe por qr_token si existe; si no, lista normal
    if "qr_token" in cols:
        key_expr = "COALESCE(qr_token, id::text)"
        # score “anti-fantasma”
        score = []
        if "items_json" in cols:
            score.append("(CASE WHEN items_json IS NULL THEN 0 ELSE 1 END)")
        if "mp_status" in cols:
            score.append("(CASE WHEN mp_status IS NULL THEN 0 ELSE 1 END)")
        score.append("(CASE WHEN status='PAID' THEN 1 ELSE 0 END)")
        score_sql = " + ".join(score) if score else "0"

        sql = f"""
        SELECT DISTINCT ON ({key_expr})
               {', '.join(select_cols)}
          FROM public.orders
         WHERE auth_provider=%s AND auth_subject=%s
         ORDER BY {key_expr}, ({score_sql}) DESC, created_at DESC NULLS LAST
         LIMIT %s
        """
        rows = fetchall(sql, (auth_provider, auth_subject, int(limit)))
    else:
        sql = f"""
        SELECT {', '.join(select_cols)}
          FROM public.orders
         WHERE auth_provider=%s AND auth_subject=%s
         ORDER BY created_at DESC NULLS LAST
         LIMIT %s
        """
        rows = fetchall(sql, (auth_provider, auth_subject, int(limit)))

    # normalizar id a str (uuid)
    for r in rows:
        if "id" in r and r["id"] is not None:
            r["id"] = str(r["id"])
    return rows


def get_order_by_id(order_id: str) -> dict[str, Any] | None:
    if not pg_table_exists("orders"):
        return None

    cols = pg_columns("orders")
    want = [
        "id","event_slug","created_at","status","total_amount","total_cents",
        "currency","qr_token","paid_at","items_json","mp_status","mp_payment_id",
        "pickup_code","auth_provider","auth_subject","sale_item_id","ticket_type_id"
    ]
    select_cols = [c for c in want if c in cols]
    if "id" not in select_cols:
        select_cols.insert(0, "id")

    sql = f"SELECT {', '.join(select_cols)} FROM public.orders WHERE id=%s LIMIT 1"
    row = fetchone(sql, (str(order_id),))
    if not row:
        return None
    row["id"] = str(row["id"])
    return row


def get_item_name_for_order(order_row: dict[str, Any]) -> str | None:
    event_slug = (order_row.get("event_slug") or "").strip()
    if not event_slug:
        return None

    # 1) sale_items si existe
    sale_item_id = order_row.get("sale_item_id")
    if sale_item_id and pg_table_exists("sale_items"):
        cols = pg_columns("sale_items")
        if {"id","name","event_slug"}.issubset(cols):
            r = fetchone(
                "SELECT name FROM public.sale_items WHERE event_slug=%s AND id=%s LIMIT 1",
                (event_slug, int(sale_item_id)),
            )
            if r and r.get("name"):
                return r["name"]

    # 2) ticket_types si existe
    ticket_type_id = order_row.get("ticket_type_id")
    if ticket_type_id and pg_table_exists("ticket_types"):
        cols = pg_columns("ticket_types")
        if {"id","name","event_slug"}.issubset(cols):
            r = fetchone(
                "SELECT name FROM public.ticket_types WHERE event_slug=%s AND id=%s LIMIT 1",
                (event_slug, int(ticket_type_id)),
            )
            if r and r.get("name"):
                return r["name"]

    return None
