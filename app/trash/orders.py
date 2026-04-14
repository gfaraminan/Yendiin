from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from app.db import get_conn

router = APIRouter(tags=["orders"])


# -------------------------
# helpers (schema-safe)
# -------------------------

def _table_columns(cur, table: str) -> set[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table,),
    )
    rows = cur.fetchall() or []
    if not rows:
        return set()
    if isinstance(rows[0], dict):
        return {r["column_name"] for r in rows}
    return {r[0] for r in rows}


def _rows_to_dicts(cur, rows):
    if not rows:
        return []
    if isinstance(rows[0], dict):
        return rows
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


def _now_epoch_s() -> int:
    return int(time.time())


# -------------------------
# models
# -------------------------

class OrderCreate(BaseModel):
    tenant_id: str = Field(default="default")
    event_slug: str
    sale_item_id: int
    quantity: int = Field(default=1, ge=1, le=20)  # demo-safe cap
    payment_method: str = Field(default="DEMO")  # "MP" | "CARD" | "DEMO"


# -------------------------
# endpoints
# -------------------------

@router.post("/create")
def create_order(payload: OrderCreate, request: Request):
    """
    Crea orden PAID (demo) y emite 1 ticket por cada unidad comprada.

    Fuente de verdad:
    - Totales: public.orders (SUM total_cents)
    - Entradas emitidas: public.issued_tickets (conteo real por ticket)

    Nota: Implementación schema-safe (solo inserta columnas existentes).
    """
    user = request.session.get("user") or {}
    # esperamos que auth setee sub/email/name
    if not user or not user.get("sub"):
        raise HTTPException(status_code=401, detail="login_required")

    tenant_id = (payload.tenant_id or "default").strip() or "default"
    event_slug = payload.event_slug.strip()

    with get_conn() as conn:
        cur = conn.cursor()

        # --- schema awareness
        orders_cols = _table_columns(cur, "orders")
        sale_cols = _table_columns(cur, "sale_items")
        tickets_cols = _table_columns(cur, "issued_tickets")

        # --- 1) lock sale_item row (stock)
        # columns we try to read (fallbacks handled below)
        sale_select = []
        for c in ["id", "tenant", "event_slug", "name", "price_cents", "stock_total", "stock_sold", "active", "ticket_type_id"]:
            if c in sale_cols:
                sale_select.append(c)

        if "id" not in sale_select or "price_cents" not in sale_select:
            raise HTTPException(status_code=500, detail="Schema inválido: sale_items")

        cur.execute(
            f"""
            SELECT {", ".join(sale_select)}
            FROM sale_items
            WHERE id = %s AND event_slug = %s
            FOR UPDATE
            """,
            (payload.sale_item_id, event_slug),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="item_not_found")

        item = row if isinstance(row, dict) else dict(zip([d[0] for d in cur.description], row))

        if item.get("active") is False:
            raise HTTPException(status_code=404, detail="item_inactive")

        stock_total = int(item.get("stock_total") or 0)
        stock_sold = int(item.get("stock_sold") or 0)
        # stock_total = 0 => sin límite (útil para 'extras' sin cupo).
        if stock_total > 0 and (stock_sold + payload.quantity) > stock_total:
            remaining = max(stock_total - stock_sold, 0)
            raise HTTPException(status_code=400, detail=f"Sin stock. Quedan {remaining}.")

        price_cents = int(item.get("price_cents") or 0)
        total_cents = price_cents * int(payload.quantity)

        # --- 2) insert order (schema-safe)
        order_id = str(uuid.uuid4())

        # normalize status (dashboard expects PAID)
        status_value = "PAID"

        # items_json in this project is an object, not an array
        items_json: Dict[str, Any] = {
            "qty": int(payload.quantity),
            "unit_amount": price_cents,
            "total": total_cents,
            "service_fee": 0,
            "sale_item_id": int(payload.sale_item_id),
            "event_slug": event_slug,
            "ticket_type_id": int(item.get("ticket_type_id") or 0) or None,
        }

        order_data: Dict[str, Any] = {}

        # minimal set with fallbacks across schema variants
        if "id" in orders_cols: order_data["id"] = order_id
        if "tenant_id" in orders_cols: order_data["tenant_id"] = tenant_id
        if "tenant" in orders_cols: order_data["tenant"] = tenant_id
        if "event_slug" in orders_cols: order_data["event_slug"] = event_slug
        if "status" in orders_cols: order_data["status"] = status_value
        if "bar_slug" in orders_cols: order_data["bar_slug"] = None  # entradas (no barra)
        if "created_at" in orders_cols: order_data["created_at"] = None  # let DB default if possible

        # totals (use total_cents + total_amount fallback)
        if "total_cents" in orders_cols: order_data["total_cents"] = total_cents
        if "total_amount" in orders_cols and "total_cents" not in orders_cols:
            order_data["total_amount"] = round(total_cents / 100, 2)

        if "items_json" in orders_cols: order_data["items_json"] = items_json

        # customer identity
        customer_id = str(user.get("sub"))
        if "customer_id" in orders_cols: order_data["customer_id"] = customer_id
        if "auth_provider" in orders_cols: order_data["auth_provider"] = user.get("provider", "google")
        if "auth_subject" in orders_cols: order_data["auth_subject"] = user.get("sub")
        if "customer_label" in orders_cols: order_data["customer_label"] = user.get("name") or user.get("email")

        # remove None created_at if DB has default; otherwise we'll set now()
        if "created_at" in order_data and order_data["created_at"] is None:
            # if DB requires not null and no default, set to now()
            # safest: omit and let DB default if exists
            order_data.pop("created_at", None)

        ins_cols = list(order_data.keys())
        ins_vals = [order_data[k] for k in ins_cols]
        if not ins_cols:
            raise HTTPException(status_code=500, detail="Schema inválido: orders")

        placeholders = ", ".join(["%s"] * len(ins_cols))
        cur.execute(
            f"""INSERT INTO orders ({", ".join(ins_cols)}) VALUES ({placeholders})""",
            tuple(ins_vals),
        )

        # --- 3) update stock_sold (if exists)
        if "stock_sold" in sale_cols:
            cur.execute(
                """
                UPDATE sale_items
                SET stock_sold = COALESCE(stock_sold, 0) + %s
                WHERE id = %s
                """,
                (int(payload.quantity), int(payload.sale_item_id)),
            )

        # --- 4) issue N tickets (1 per unit)
        # required columns in issued_tickets:
        required = {"id", "tenant", "order_id", "event_slug", "sale_item_id"}
        if not required.issubset(tickets_cols):
            raise HTTPException(status_code=500, detail="Schema inválido: issued_tickets")

        ticket_type_id = item.get("ticket_type_id")
        tickets: List[Dict[str, Any]] = []
        now_s = _now_epoch_s()

        for _ in range(int(payload.quantity)):
            tid = str(uuid.uuid4())
            tdata: Dict[str, Any] = {
                "id": tid,
                "tenant": tenant_id if "tenant" in tickets_cols else None,
                "tenant_id": tenant_id if "tenant_id" in tickets_cols else None,
                "order_id": str(order_id),
                "event_slug": event_slug,
                "sale_item_id": int(payload.sale_item_id),
                "ticket_type_id": int(ticket_type_id) if (ticket_type_id and "ticket_type_id" in tickets_cols) else None,
                "courtesy": 0 if "courtesy" in tickets_cols else None,
                "status": "ISSUED" if "status" in tickets_cols else None,
                "created_at": now_s if "created_at" in tickets_cols else None,
            }
            # drop None + unknown cols
            tcols = [k for k, v in tdata.items() if v is not None and k in tickets_cols]
            tvals = [tdata[k] for k in tcols]
            cur.execute(
                f"""INSERT INTO issued_tickets ({", ".join(tcols)}) VALUES ({", ".join(["%s"] * len(tcols))})""",
                tuple(tvals),
            )
            tickets.append({
                "ticket_id": tid,
                "qr_payload": f"ticketera://ticket/{tid}",
            })

        conn.commit()

        return {
            "ok": True,
            "order_id": order_id,
            "event_slug": event_slug,
            "sale_item_id": int(payload.sale_item_id),
            "quantity": int(payload.quantity),
            "total_cents": total_cents,
            "tickets": tickets,
        }
