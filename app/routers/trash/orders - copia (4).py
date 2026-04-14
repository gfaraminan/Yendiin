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
    """Return column names for a table.

    Works with tuple rows (default cursor) and dict-like rows (DictCursor/RealDictCursor).
    """
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

    first = rows[0]
    if isinstance(first, dict):
        out: set[str] = set()
        for r in rows:
            if not r:
                continue
            v = r.get("column_name")
            if v is None and len(r):
                v = next(iter(r.values()))
            if v:
                out.add(str(v))
        return out

    out: set[str] = set()
    for r in rows:
        if not r:
            continue
        v = r[0] if len(r) else None
        if v:
            out.add(str(v))
    return out




def _table_exists(cur, table: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table,),
    )
    return cur.fetchone() is not None
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
    try:

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

            # Si el usuario está logueado (Google), guardamos identidad en la orden.
            # Esto habilita "Mis Tickets" sin depender de customer_label.
            user = (request.session.get("user") or {}) if hasattr(request, "session") else {}
            if user:
                add("auth_provider", user.get("provider"))
                add("auth_subject", user.get("sub"))
                # customer_id: usamos sub como identificador estable si la columna existe
                add("customer_id", user.get("sub"))
                # customer_label: preferimos email del usuario
                add("customer_label", user.get("email") or (payload.buyer_email if hasattr(payload, "buyer_email") else None))


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
    except HTTPException:
        raise
    except Exception as e:
        # Garantiza JSON para errores inesperados (evita 'Internal Server Error' texto plano)
        raise HTTPException(status_code=500, detail=f"internal_error: {type(e).__name__}: {e}")
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
# PRO: "Mis tickets" + "Mis consumos" (cliente)
# Devuelve Entradas + Barra unificados como assets.
# -------------------------
@router.get("/my-assets")
def my_assets(
    request: Request,
    tenant_id: str = Query(default="default", alias="tenant"),
):
    tenant_id = _norm_tenant_id(tenant_id)

    user = getattr(request, "session", {}).get("user")
    if not user or not user.get("email"):
        raise HTTPException(status_code=401, detail="not_authenticated")

    email = str(user["email"]).strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="not_authenticated")

    assets: list[dict] = []

    with get_conn() as conn:
        cur = conn.cursor()

        # schema checks
        if not _table_exists(cur, "orders"):
            raise HTTPException(status_code=500, detail="Schema inválido: orders no existe")

        ocols = _table_columns(cur, "orders")

        # Cómo matcheamos órdenes al usuario:
        # 1) por auth_provider/auth_subject (ideal, si existe en DB y en sesión)
        # 2) fallback por customer_label == email (compat con órdenes viejas)
        user_where_parts: list[str] = []
        user_where_args: list[Any] = []

        prov = user.get("provider") or user.get("auth_provider") or user.get("authProvider")
        sub = user.get("sub") or user.get("auth_subject") or user.get("authSubject")

        if prov and sub and ("auth_provider" in ocols) and ("auth_subject" in ocols):
            user_where_parts.append("(o.auth_provider = %s AND o.auth_subject = %s)")
            user_where_args.extend([str(prov), str(sub)])

        if "customer_label" in ocols and email:
            user_where_parts.append("(o.customer_label IS NOT NULL AND lower(o.customer_label) = lower(%s))")
            user_where_args.append(email)

        if "customer_id" in ocols:
            cid = user.get("customer_id") or user.get("customerId")
            if cid:
                user_where_parts.append("(o.customer_id = %s)")
                user_where_args.append(str(cid))

        if not user_where_parts:
            # No hay forma segura de filtrar órdenes para este usuario -> devolvemos vacío
            return {"ok": True, "assets": [], "tickets": [], "bar": []}

        user_where_sql = " OR ".join(user_where_parts)


        has_events = _table_exists(cur, "events")
        has_tickets = _table_exists(cur, "tickets")

        # -------- ENTRADAS (tickets) --------
        if has_tickets:
            if has_events:
                cur.execute(
                    f\"\"\"
                    SELECT
                      t.id, t.event_slug, t.sale_item_id, t.qr_token, t.status, t.created_at, t.used_at,
                      o.id AS order_id, o.total_cents,
                      e.title AS event_title, e.date_text, e.venue, e.city,
                      COALESCE(e.flyer_url, e.hero_bg) AS flyer_url
                    FROM tickets t
                    JOIN orders o ON o.id = t.order_id
                    LEFT JOIN events e ON e.slug = t.event_slug AND e.tenant_id = o.tenant_id
                    WHERE o.tenant_id = %s
                      AND ({user_where_sql})
                    ORDER BY t.created_at DESC
                    """,
                    (tenant_id, *user_where_args),
                )
            else:
                cur.execute(
                    f\"\"\"
                    SELECT
                      t.id, t.event_slug, t.sale_item_id, t.qr_token, t.status, t.created_at, t.used_at,
                      o.id AS order_id, o.total_cents
                    FROM tickets t
                    JOIN orders o ON o.id = t.order_id
                    WHERE o.tenant_id = %s
                      AND ({user_where_sql})
                    ORDER BY t.created_at DESC
                    """,
                    (tenant_id, *user_where_args),
                )

            rows = _rows_to_dicts(cur, cur.fetchall() or [])
            for r in rows:
                qr_token = r.get("qr_token")
                assets.append(
                    {
                        "kind": "entradas",
                        "id": str(r.get("id")),
                        "order_id": str(r.get("order_id")),
                        "event_slug": r.get("event_slug"),
                        "title": r.get("event_title") or r.get("event_slug") or "Entrada",
                        "date_text": r.get("date_text"),
                        "venue": r.get("venue"),
                        "city": r.get("city"),
                        "flyer_url": r.get("flyer_url"),
                        "sale_item_id": r.get("sale_item_id"),
                        "status": r.get("status") or "valid",
                        "created_at": r.get("created_at"),
                        "used_at": r.get("used_at"),
                        "total": (int(r.get("total_cents") or 0) / 100.0),
                        "qr_token": qr_token,
                        "qr_payload": f"TICKETPRO:ENTRADAS:{qr_token}" if qr_token else "",
                    }
                )

        # -------- BARRA (derivado desde orders) --------
        # La "barra" se identifica desde orders por:
        # source='bar' o bar_slug NOT NULL o order_kind/kind contiene 'bar'
        where_bar = []
        if "source" in ocols:
            where_bar.append("COALESCE(o.source,'') = 'bar'")
        if "bar_slug" in ocols:
            where_bar.append("o.bar_slug IS NOT NULL")
        if "order_kind" in ocols:
            where_bar.append("COALESCE(o.order_kind,'') ILIKE 'bar'")
        if "kind" in ocols:
            where_bar.append("COALESCE(o.kind,'') ILIKE 'bar'")

        if where_bar:
            where_bar_sql = " OR ".join(where_bar)

            if has_events and "event_slug" in ocols:
                cur.execute(
                    f"""
                    SELECT
                      o.id AS order_id,
                      o.created_at,
                      o.status,
                      o.total_cents,
                      o.event_slug,
                      e.title AS event_title, e.date_text, e.venue, e.city,
                      COALESCE(e.flyer_url, e.hero_bg) AS flyer_url
                    FROM orders o
                    LEFT JOIN events e ON e.slug = o.event_slug AND e.tenant_id = o.tenant_id
                    WHERE o.tenant_id = %s
                      AND ({user_where_sql})
                      AND ({where_bar_sql})
                    ORDER BY o.created_at DESC
                    """,
                    (tenant_id, *user_where_args),
                )
            else:
                select_event = ", o.event_slug" if ("event_slug" in ocols) else ""
                cur.execute(
                    f"""
                    SELECT
                      o.id AS order_id,
                      o.created_at,
                      o.status,
                      o.total_cents
                      {select_event}
                    FROM orders o
                    WHERE o.tenant_id = %s
                      AND ({user_where_sql})
                      AND ({where_bar_sql})
                    ORDER BY o.created_at DESC
                    """,
                    (tenant_id, *user_where_args),
                )

            rows = _rows_to_dicts(cur, cur.fetchall() or [])
            for r in rows:
                order_id = str(r.get("order_id"))
                st = (r.get("status") or "").strip()

                norm = "valid"
                if st:
                    st_low = st.lower()
                    if "cancel" in st_low:
                        norm = "cancelled"
                    elif "request" in st_low:
                        norm = "cancel_requested"
                    elif st_low in ("used", "consumed"):
                        norm = "used"
                    else:
                        norm = "valid"

                assets.append(
                    {
                        "kind": "barra",
                        "id": order_id,
                        "order_id": order_id,
                        "event_slug": r.get("event_slug"),
                        "title": r.get("event_title") or "Barra",
                        "date_text": r.get("date_text"),
                        "venue": r.get("venue"),
                        "city": r.get("city"),
                        "flyer_url": r.get("flyer_url"),
                        "status": norm,
                        "created_at": r.get("created_at"),
                        "used_at": None,
                        "total": (int(r.get("total_cents") or 0) / 100.0),
                        "qr_token": None,
                        "qr_payload": f"TICKETPRO:BARRA:ORDER:{order_id}",
                    }
                )

    return {"ok": True, "assets": assets}


# -------------------------
# PRO: arrepentimiento (manual)
# Marca solicitud y deja nota si hay columna.
# -------------------------
class CancelRequestIn(BaseModel):
    kind: str = "entradas"  # entradas | barra
    id: str | None = None   # ticket_id (entradas) o order_id (barra)
    order_id: str | None = None
    reason: str | None = None


@router.post("/cancel-request")
def cancel_request(
    request: Request,
    payload: CancelRequestIn,
    tenant_id: str = Query(default="default", alias="tenant"),
):
    tenant_id = _norm_tenant_id(tenant_id)

    user = getattr(request, "session", {}).get("user")
    if not user or not user.get("email"):
        raise HTTPException(status_code=401, detail="not_authenticated")

    email = str(user["email"]).strip().lower()

    kind = (payload.kind or "entradas").strip().lower()
    reason = (payload.reason or "").strip()

    with get_conn() as conn:
        cur = conn.cursor()
        ocols = _table_columns(cur, "orders")

        # ---- ENTRADAS: marcar ticket ----
        if kind == "entradas":
            ticket_id = (payload.id or "").strip()
            if not ticket_id:
                raise HTTPException(status_code=400, detail="missing_ticket_id")

            cur.execute(
                """
                SELECT t.id, t.status, t.order_id
                FROM tickets t
                JOIN orders o ON o.id = t.order_id
                WHERE o.tenant_id = %s
                  AND ({user_where_sql})
                  AND t.id = %s
                LIMIT 1
                """,
                (tenant_id, *user_where_args, ticket_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="ticket_not_found")

            tcols = _table_columns(cur, "tickets")
            if "status" in tcols:
                cur.execute("UPDATE tickets SET status='cancel_requested' WHERE id=%s", (ticket_id,))

            # nota opcional en orders
            order_id = row["order_id"] if isinstance(row, dict) else row[2]
            if reason and ("notes" in ocols or "note" in ocols or "cancel_reason" in ocols):
                col = "notes" if "notes" in ocols else ("note" if "note" in ocols else "cancel_reason")
                cur.execute(
                    f"UPDATE orders SET {col} = COALESCE({col}, '') || %s WHERE tenant_id=%s AND id=%s",
                    (f"\n[ARREPENTIMIENTO] {reason}", tenant_id, order_id),
                )

            conn.commit()
            return {"ok": True}

        # ---- BARRA: marcar orden ----
        order_id = (payload.order_id or payload.id or "").strip()
        if not order_id:
            raise HTTPException(status_code=400, detail="missing_order_id")

        cur.execute(
            """
            SELECT id
            FROM orders
            WHERE tenant_id=%s AND id=%s AND lower(buyer_email)=lower(%s)
            LIMIT 1
            """,
            (tenant_id, order_id, email),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="order_not_found")

        if "status" in ocols:
            cur.execute("UPDATE orders SET status='CANCEL_REQUESTED' WHERE tenant_id=%s AND id=%s", (tenant_id, order_id))

        if reason and ("notes" in ocols or "note" in ocols or "cancel_reason" in ocols):
            col = "notes" if "notes" in ocols else ("note" if "note" in ocols else "cancel_reason")
            cur.execute(
                f"UPDATE orders SET {col} = COALESCE({col}, '') || %s WHERE tenant_id=%s AND id=%s",
                (f"\n[ARREPENTIMIENTO] {reason}", tenant_id, order_id),
            )

        conn.commit()
        return {"ok": True}


# -------------------------
# PRO: transferir compra (manual) - cambia buyer_email en orders
# -------------------------
class TransferOrderIn(BaseModel):
    order_id: str
    to_email: str


@router.post("/transfer-order")
def transfer_order(
    request: Request,
    payload: TransferOrderIn,
    tenant_id: str = Query(default="default", alias="tenant"),
):
    tenant_id = _norm_tenant_id(tenant_id)

    user = getattr(request, "session", {}).get("user")
    if not user or not user.get("email"):
        raise HTTPException(status_code=401, detail="not_authenticated")

    from_email = str(user["email"]).strip().lower()
    to_email = (payload.to_email or "").strip().lower()
    if not to_email or "@" not in to_email:
        raise HTTPException(status_code=400, detail="invalid_to_email")

    with get_conn() as conn:
        cur = conn.cursor()
        ocols = _table_columns(cur, "orders")

        cur.execute(
            "SELECT id FROM orders WHERE tenant_id=%s AND id=%s AND lower(buyer_email)=lower(%s) LIMIT 1",
            (tenant_id, payload.order_id, from_email),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="order_not_found")

        cur.execute(
            "UPDATE orders SET buyer_email=%s WHERE tenant_id=%s AND id=%s",
            (to_email, tenant_id, payload.order_id),
        )
        conn.commit()

    return {"ok": True}


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