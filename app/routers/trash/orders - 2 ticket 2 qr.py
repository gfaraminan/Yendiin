from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
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


def _norm_tenant_id(tenant_id: str) -> str:
    return (tenant_id or "").strip() or "default"


# -------------------------
# models
# -------------------------
class BuyerIn(BaseModel):
    full_name: Optional[str] = None
    dni: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class OrderItemIn(BaseModel):
    sale_item_id: int = Field(..., description="ID del item/entrada a comprar")
    quantity: int = Field(1, ge=1, le=20, description="Cantidad")


class OrderCreate(BaseModel):
    # compat: algunos front mandan tenant, otros tenant_id
    tenant_id: str = Field("default", min_length=1)
    event_slug: str = Field(..., min_length=1)

    # compat: modo simple
    sale_item_id: Optional[int] = None
    quantity: int = Field(1, ge=1, le=20)

    # modo múltiple
    items: Optional[List[OrderItemIn]] = None

    payment_method: str = Field("cash", description="cash|card|mp|transfer")
    buyer: Optional[BuyerIn] = None


# -------------------------
# endpoints
# -------------------------
@router.post("/create")
def create_order(
    payload: OrderCreate,
    request: Request,
    # compat: si algún front llama /create?tenant=default
    tenant_q: Optional[str] = Query(default=None, alias="tenant"),
):
    """
    Crea una orden y devuelve JSON SIEMPRE.
    (En demo: checkout_url = null. La confirmación/pago real va después.)
    """

    tenant_id = _norm_tenant_id(payload.tenant_id)
    if tenant_q:
        # prioridad a query param si viene, para no romper UIs viejas
        tenant_id = _norm_tenant_id(tenant_q)

    event_slug = (payload.event_slug or "").strip()
    if not event_slug:
        raise HTTPException(status_code=400, detail="event_slug requerido")

    # Normalizamos items (acepta modo simple o múltiple)
    items = payload.items
    if not items:
        if payload.sale_item_id is None:
            raise HTTPException(status_code=400, detail="Falta sale_item_id o items")
        items = [OrderItemIn(sale_item_id=payload.sale_item_id, quantity=payload.quantity)]

    with get_conn() as conn:
        cur = conn.cursor()

        # 1) Buscar evento por tenant_id+slug (plataforma)
        ev_cols = _table_columns(cur, "events")
        if "tenant" not in ev_cols:
            raise HTTPException(status_code=500, detail="Schema inválido: events.tenant no existe")

        cur.execute(
            """
            SELECT slug, title, tenant
            FROM events
            WHERE tenant_id=%s AND slug=%s AND active=TRUE
            LIMIT 1
            """,
            (tenant_id, event_slug),
        )
        ev = cur.fetchone()
        if not ev:
            raise HTTPException(status_code=404, detail="Evento no encontrado")

        # owner real del evento (producer)
        owner_tenant = (ev["tenant"] if isinstance(ev, dict) else ev[2]) or ""
        owner_tenant = owner_tenant.strip()
        if not owner_tenant:
            raise HTTPException(status_code=500, detail="Evento sin owner (events.tenant vacío)")

        # 2) Leer sale_items del owner + evento
        si_cols = _table_columns(cur, "sale_items")
        required = {"id", "name", "price_cents", "active", "tenant", "event_slug"}
        missing = [c for c in required if c not in si_cols]
        if missing:
            raise HTTPException(status_code=500, detail=f"Schema inválido sale_items faltan: {missing}")

        has_kind = "kind" in si_cols
        has_stock_total = "stock_total" in si_cols
        has_stock_sold = "stock_sold" in si_cols

        order_items: List[Dict[str, Any]] = []
        total_cents = 0

        for it in items:
            qty = int(it.quantity or 0)
            if qty <= 0:
                continue

            params = [owner_tenant, event_slug, int(it.sale_item_id)]
            where_kind = "AND kind='ticket'" if has_kind else ""
            cur.execute(
                f"""
                SELECT id, name, price_cents, active
                       {", stock_total" if has_stock_total else ""}
                       {", stock_sold" if has_stock_sold else ""}
                FROM sale_items
                WHERE tenant=%s AND event_slug=%s AND id=%s
                  AND active=TRUE
                  {where_kind}
                LIMIT 1
                """,
                tuple(params),
            )
            si = cur.fetchone()
            if not si:
                raise HTTPException(status_code=404, detail=f"Item {it.sale_item_id} no encontrado/activo")

            if isinstance(si, dict):
                unit_cents = int(si.get("price_cents") or 0)
                name = si.get("name") or "Ticket"
                stock_total = si.get("stock_total") if has_stock_total else None
                stock_sold = si.get("stock_sold") if has_stock_sold else None
                sale_item_id = int(si["id"])
            else:
                # fallback por si no viene dict
                sale_item_id = int(si[0])
                name = si[1]
                unit_cents = int(si[2] or 0)
                stock_total = si[4] if has_stock_total else None
                stock_sold = si[5] if has_stock_sold else None

            # validación stock si existen columnas
            if has_stock_total and stock_total is not None:
                sold = int(stock_sold or 0) if has_stock_sold else 0
                available = int(stock_total) - sold
                if qty > available:
                    raise HTTPException(status_code=400, detail=f"Stock insuficiente para {name}")

            line_total_cents = unit_cents * qty
            total_cents += line_total_cents

            order_items.append(
                {
                    "sale_item_id": sale_item_id,
                    "name": name,
                    "qty": qty,
                    "unit_price_cents": unit_cents,
                    "unit_price": unit_cents / 100.0,
                    "line_total_cents": line_total_cents,
                    "line_total": line_total_cents / 100.0,
                }
            )

        if not order_items:
            raise HTTPException(status_code=400, detail="No hay items válidos en la orden")

        # 3) Reservar stock (simple): incrementa stock_sold si existe
        if has_stock_total and has_stock_sold:
            for oi in order_items:
                cur.execute(
                    """
                    UPDATE sale_items
                    SET stock_sold = stock_sold + %s
                    WHERE tenant=%s AND event_slug=%s AND id=%s
                      AND (stock_total IS NULL OR stock_sold + %s <= stock_total)
                    """,
                    (oi["qty"], owner_tenant, event_slug, oi["sale_item_id"], oi["qty"]),
                )
                if cur.rowcount != 1:
                    raise HTTPException(status_code=400, detail=f"Stock insuficiente (race) para {oi['name']}")

        # 4) Insert order (schema-safe)
        order_id = str(uuid.uuid4())
        orders_cols = _table_columns(cur, "orders")

        # armamos insert dinámico según columnas disponibles
        cols = []
        vals = []
        args = []

        def add(col: str, val: Any):
            if col in orders_cols:
                cols.append(col)
                vals.append("%s")
                args.append(val)

        add("id", order_id)
        add("tenant_id", tenant_id)
        add("event_slug", event_slug)
        add("producer_tenant", owner_tenant)  # si existe
        add("items_json", json.dumps(order_items))
        add("total_cents", int(total_cents))
        add("status", "pending")
        add("payment_method", payload.payment_method)
        add("buyer_email", (payload.buyer.email if payload.buyer else None))
        add("buyer_name", (payload.buyer.full_name if payload.buyer else None))
        add("created_at", None)  # si existe como timestamptz default, mejor no setear

        if "created_at" in orders_cols:
            # si created_at existe, lo seteamos con NOW() si el insert lo permite
            # (evitamos pasar None)
            cols2, vals2, args2 = [], [], []
            for c, v, a in zip(cols, vals, args):
                if c == "created_at":
                    cols2.append("created_at")
                    vals2.append("NOW()")
                else:
                    cols2.append(c)
                    vals2.append(v)
                    args2.append(a)
            cols, vals, args = cols2, vals2, args2

        if not cols:
            raise HTTPException(status_code=500, detail="Schema inválido: tabla orders sin columnas esperadas")

        sql = f"INSERT INTO orders ({', '.join(cols)}) VALUES ({', '.join(vals)})"
        cur.execute(sql, tuple(args))

        # -------------------------
        # 5) PRO: crear tickets persistidos (1 por entrada/unidad)
        # -------------------------
        tickets_cols = _table_columns(cur, "tickets")
        needed_tickets = {"id", "order_id", "tenant_id", "producer_tenant", "event_slug", "sale_item_id", "qr_token", "status"}
        missing_tickets = [c for c in needed_tickets if c not in tickets_cols]
        if missing_tickets:
            raise HTTPException(status_code=500, detail=f"Schema inválido tickets faltan: {missing_tickets}")

        tickets_out: List[Dict[str, Any]] = []
        for oi in order_items:
            qty = int(oi.get("qty") or 0)
            for _ in range(qty):
                ticket_id = str(uuid.uuid4())
                qr_token = uuid.uuid4().hex  # token único para QR

                cur.execute(
                    """
                    INSERT INTO tickets (id, order_id, tenant_id, producer_tenant, event_slug, sale_item_id, qr_token, status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,'valid')
                    """,
                    (
                        ticket_id,
                        order_id,
                        tenant_id,
                        owner_tenant,
                        event_slug,
                        int(oi["sale_item_id"]),
                        qr_token,
                    ),
                )

                tickets_out.append(
                    {
                        "ticket_id": ticket_id,
                        "qr_token": qr_token,
                        "event_slug": event_slug,
                        "sale_item_id": int(oi["sale_item_id"]),
                        "name": oi.get("name"),
                    }
                )

        conn.commit()

    resp = {
        "ok": True,
        "order_id": order_id,
        "tenant_id": tenant_id,
        "event_slug": event_slug,
        "owner_tenant": owner_tenant,
        "items": order_items,
        "total_cents": total_cents,
        "total": total_cents / 100.0,
        "checkout_url": None,  # demo
        "tickets": tickets_out,  # ✅ PRO
    }

    # Compat legacy: si tu front viejo esperaba 1 QR en vez de lista
    if tickets_out:
        resp["qr"] = tickets_out[0]["qr_token"]

    return resp


# -------------------------
# PRO: "Mis tickets" (cliente)
# -------------------------
@router.get("/my-tickets")
def my_tickets(
    request: Request,
    tenant_id: str = Query(default="default", alias="tenant"),
):
    """
    Devuelve los tickets del usuario logueado (por sesión),
    vinculando orders.buyer_email con el email del user.
    """
    tenant_id = _norm_tenant_id(tenant_id)

    user = getattr(request, "session", {}).get("user")
    if not user or not user.get("email"):
        raise HTTPException(status_code=401, detail="not_authenticated")

    email = str(user["email"]).strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="not_authenticated")

    with get_conn() as conn:
        cur = conn.cursor()

        # chequeo schema mínimo para no romper
        tcols = _table_columns(cur, "tickets")
        ocols = _table_columns(cur, "orders")
        if "buyer_email" not in ocols:
            raise HTTPException(status_code=500, detail="Schema inválido: orders.buyer_email no existe")

        cur.execute(
            """
            SELECT
              t.id, t.event_slug, t.sale_item_id, t.qr_token, t.status, t.created_at, t.used_at,
              o.id AS order_id, o.total_cents
            FROM tickets t
            JOIN orders o ON o.id = t.order_id
            WHERE o.tenant_id = %s
              AND lower(o.buyer_email) = lower(%s)
            ORDER BY t.created_at DESC
            """,
            (tenant_id, email),
        )
        rows = cur.fetchall()
        data = _rows_to_dicts(cur, rows)

    # normalización de salida
    out = []
    for r in data:
        out.append(
            {
                "ticket_id": str(r.get("id")),
                "order_id": str(r.get("order_id")),
                "event_slug": r.get("event_slug"),
                "sale_item_id": r.get("sale_item_id"),
                "qr_token": r.get("qr_token"),
                "status": r.get("status"),
                "created_at": r.get("created_at"),
                "used_at": r.get("used_at"),
                "total_cents": r.get("total_cents"),
                "total": (int(r.get("total_cents") or 0) / 100.0),
            }
        )
    return {"ok": True, "tickets": out}


# -------------------------
# PRO: validar/consumir QR (scanner)
# -------------------------
class QRValidateIn(BaseModel):
    qr_token: str


@router.post("/validate")
def validate_qr(payload: QRValidateIn):
    """
    Valida y marca como 'used' un ticket por qr_token.
    Si ya estaba usado, devuelve valid=false.
    """
    qr_token = (payload.qr_token or "").strip()
    if not qr_token:
        raise HTTPException(status_code=400, detail="missing_qr_token")

    with get_conn() as conn:
        cur = conn.cursor()

        tcols = _table_columns(cur, "tickets")
        needed = {"id", "qr_token", "status"}
        missing = [c for c in needed if c not in tcols]
        if missing:
            raise HTTPException(status_code=500, detail=f"Schema inválido tickets faltan: {missing}")

        cur.execute(
            """
            SELECT id, status, event_slug, sale_item_id, order_id
            FROM tickets
            WHERE qr_token = %s
            LIMIT 1
            """,
            (qr_token,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="ticket_not_found")

        if isinstance(row, dict):
            ticket_id = row["id"]
            status = row["status"]
            event_slug = row.get("event_slug")
            sale_item_id = row.get("sale_item_id")
            order_id = row.get("order_id")
        else:
            ticket_id, status, event_slug, sale_item_id, order_id = row

        if status != "valid":
            return {
                "ok": True,
                "valid": False,
                "reason": f"status_{status}",
                "ticket_id": str(ticket_id),
            }

        cur.execute(
            """
            UPDATE tickets
            SET status='used', used_at=now()
            WHERE id=%s
            """,
            (ticket_id,),
        )
        conn.commit()

    return {
        "ok": True,
        "valid": True,
        "ticket_id": str(ticket_id),
        "event_slug": event_slug,
        "sale_item_id": sale_item_id,
        "order_id": str(order_id) if order_id else None,
    }
