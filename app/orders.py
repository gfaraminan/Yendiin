from __future__ import annotations

import json
import time
import uuid
import io
import os

import qrcode
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.db import get_conn as db_get_conn
from app.mailer import send_email
from app.staff_auth import require_staff_token_for_event

def _iso(v):
    """Return ISO string for datetime/date, or None."""
    if v is None:
        return None
    try:
        return v.isoformat()
    except Exception:
        return str(v)

router = APIRouter(tags=["orders"])


# ---- DB connection helper (compatible with older get_conn() signatures) ----
def _conn_cm(tenant: str | None = None):
    """Return a context manager for a DB connection.
    Some deployments expose get_conn() with no args; others accept tenant.
    """
    try:
        return db_get_conn(tenant) if tenant is not None else db_get_conn()
    except TypeError:
        # get_conn() doesn't accept tenant
        return db_get_conn()


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
    # Works for Postgres; safe because `table` is an internal constant (not user input).
    cur.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table,),
    )
    return cur.fetchone() is not None

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


def _send_transfer_notification_email(
    *,
    to_email: str,
    from_email: str,
    order_id: str,
    event_slug: str = "",
    ticket_id: str = "",
) -> None:
    event_label = event_slug or "tu evento"
    from_label = from_email or "otro usuario"
    ticket_label = ticket_id or "todos los tickets de la orden"
    subject = f"[TicketPro] Te transfirieron tickets · Orden {order_id}"
    text = (
        "¡Hola!\n\n"
        f"{from_label} te transfirió tickets en TicketPro.\n"
        f"Orden: {order_id}\n"
        f"Evento: {event_label}\n"
        f"Tickets transferidos: {ticket_label}\n\n"
        "Ingresá a Mis Tickets para verlos."
    )
    html = f"""
    <div style=\"font-family:Arial,sans-serif; line-height:1.5; color:#111;\">
      <h2>Te transfirieron tickets</h2>
      <p><strong>{from_label}</strong> te transfirió tickets en TicketPro.</p>
      <p><strong>Orden:</strong> {order_id}</p>
      <p><strong>Evento:</strong> {event_label}</p>
      <p><strong>Tickets transferidos:</strong> {ticket_label}</p>
      <p>Podés verlos desde <strong>Mis Tickets</strong>.</p>
    </div>
    """
    send_email(to_email=to_email, subject=subject, text=text, html=html)


# -------------------------
# models
# -------------------------
class BuyerIn(BaseModel):
    full_name: Optional[str] = None
    dni: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    province: Optional[str] = None
    postal_code: Optional[str] = None
    birth_date: Optional[str] = None


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
    seller_code: Optional[str] = None
    buyer: Optional[BuyerIn] = None




class TransferOrderIn(BaseModel):
    order_id: str
    to_email: str
    ticket_id: Optional[str] = None


class CancelRequestIn(BaseModel):
    kind: Optional[str] = "entrada"
    id: Optional[str] = None
    order_id: str
    reason: Optional[str] = ""


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

        buyer_phone = ""
        if payload.buyer and payload.buyer.phone:
            buyer_phone = "".join(ch for ch in str(payload.buyer.phone) if ch.isdigit())
        if len(buyer_phone) < 8:
            raise HTTPException(status_code=400, detail="El celular de contacto es obligatorio")

        buyer_dni = ""
        if payload.buyer and payload.buyer.dni:
            buyer_dni = "".join(ch for ch in str(payload.buyer.dni) if ch.isdigit())

        with _conn_cm() as conn:
            cur = conn.cursor()

            # 1) Buscar evento por tenant_id+slug (plataforma)
            ev_cols = _table_columns(cur, "events")
            if "tenant" not in ev_cols:
                raise HTTPException(status_code=500, detail="Schema inválido: events.tenant no existe")

            sold_out_select = ", COALESCE(sold_out, FALSE) AS sold_out" if "sold_out" in ev_cols else ""
            cur.execute(
                f"""
                SELECT slug, title, tenant{sold_out_select}
                FROM events
                WHERE tenant_id=%s AND slug=%s AND active=TRUE
                LIMIT 1
                """,
                (tenant_id, event_slug),
            )
            ev = cur.fetchone()
            if not ev:
                raise HTTPException(status_code=404, detail="Evento no encontrado")

            event_sold_out = bool(ev.get("sold_out", False)) if isinstance(ev, dict) else (bool(ev[3]) if len(ev) > 3 else False)
            if event_sold_out:
                raise HTTPException(status_code=409, detail="sold_out")

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
                        "buyer_phone": buyer_phone,
                        "buyer_dni": buyer_dni,
                        "buyer_address": (payload.buyer.address if payload.buyer else None),
                        "buyer_province": (payload.buyer.province if payload.buyer else None),
                        "buyer_postal_code": (payload.buyer.postal_code if payload.buyer else None),
                        "buyer_birth_date": (payload.buyer.birth_date if payload.buyer else None),
                    }
                )

            if not order_items:
                raise HTTPException(status_code=400, detail="No hay items válidos en la orden")

            # 3) Insert order (schema-safe)
            order_id = str(uuid.uuid4())
            orders_cols = _table_columns(cur, "orders")

            # Si el usuario está logueado (Google), guardamos identidad en la orden.
            # Esto habilita "Mis Tickets" sin depender de customer_label.
            user = (request.session.get("user") or {}) if hasattr(request, "session") else {}

            # armamos insert dinámico según columnas disponibles
            cols = []
            vals = []
            args = []

            def add(col: str, val: Any):
                if col in orders_cols:
                    cols.append(col)
                    vals.append("%s")
                    args.append(val)

            if user:
                add("auth_provider", user.get("provider"))
                add("auth_subject", user.get("sub"))
                # customer_id: usamos sub como identificador estable si la columna existe
                add("customer_id", user.get("sub"))
                # customer_label: preferimos email del usuario
                add("customer_label", user.get("email") or (payload.buyer_email if hasattr(payload, "buyer_email") else None))

            add("id", order_id)
            add("tenant_id", tenant_id)
            add("event_slug", event_slug)
            add("producer_tenant", owner_tenant)  # si existe
            add("items_json", json.dumps(order_items))
            add("total_cents", int(total_cents))
            add("status", "pending")
            add("payment_method", payload.payment_method)
            add("seller_code", (payload.seller_code or None))
            add("buyer_email", (payload.buyer.email if payload.buyer else None))
            add("buyer_name", (payload.buyer.full_name if payload.buyer else None))
            add("buyer_phone", buyer_phone)
            add("buyer_dni", buyer_dni)
            add("buyer_address", (payload.buyer.address if payload.buyer else None))
            add("buyer_province", (payload.buyer.province if payload.buyer else None))
            add("buyer_postal_code", (payload.buyer.postal_code if payload.buyer else None))
            add("buyer_birth_date", (payload.buyer.birth_date if payload.buyer else None))
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
            "checkout_url": None,  # se genera con /api/payments/mp/create-preference
        }

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

    with _conn_cm() as conn:
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
              AND lower(o.status) = 'paid'
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
def my_assets(request: Request, tenant: str = Query("default"), order_id: Optional[str] = Query(default=None)):
    """Devuelve los tickets/entradas del usuario (unificado Entradas + Barra).

    - Si el usuario está logueado: busca por auth_subject y/o buyer_email.
    - Si NO está logueado (guest): permite recuperar SOLO la última orden de esta sesión si viene order_id
      y coincide con session["last_order_id"].
    - Si viene order_id, filtra para devolver solo esa orden (mejor para pantalla "Generando QR").
    """
    user = (request.session or {}).get("user")
    auth_subject = user.get("sub") if user else None
    email = user.get("email") if user else None
    email_sess = (email or "").strip().lower() if email else None

    guest_email = None
    try:
        guest_email = request.session.get("guest_email") if getattr(request, "session", None) else None
    except Exception:
        guest_email = None
    guest_email = guest_email.strip().lower() if isinstance(guest_email, str) else None

    last_order_id = None
    try:
        last_order_id = request.session.get("last_order_id") if getattr(request, "session", None) else None
    except Exception:
        last_order_id = None

    allow_guest = (not user) and order_id and last_order_id and str(order_id) == str(last_order_id)
    if not user and not allow_guest:
        raise HTTPException(status_code=401, detail="Not authenticated")

    with _conn_cm(tenant) as conn:
        cur = conn.cursor()

        tickets_cols = set(_table_columns(cur, "tickets"))
        orders_cols = set(_table_columns(cur, "orders"))
        events_cols = set(_table_columns(cur, "events"))

        # campos opcionales por compatibilidad de schema
        t_ticket_type = "t.ticket_type" if "ticket_type" in tickets_cols else "NULL::text"
        t_qr = "t.qr_payload" if "qr_payload" in tickets_cols else "t.qr_token"

        # eventos (en distintas versiones lo guardaste con nombres diferentes)
        e_date = (
            "e.event_date" if "event_date" in events_cols else
            "e.date" if "date" in events_cols else
            "NULL::text"
        )
        e_time = (
            "e.event_time" if "event_time" in events_cols else
            "e.time" if "time" in events_cols else
            "NULL::text"
        )
        e_venue = "e.venue" if "venue" in events_cols else "NULL::text"
        e_city = "e.city" if "city" in events_cols else "NULL::text"
        e_address = "e.address" if "address" in events_cols else "NULL::text"
        e_title = "e.title" if "title" in events_cols else "NULL::text"
        o_buyer_name = "o.buyer_name" if "buyer_name" in orders_cols else "NULL::text"
        if "status" in orders_cols:
            o_paid_pred = "lower(COALESCE(o.status,'')) = 'paid'"
        elif "paid_at" in orders_cols:
            o_paid_pred = "o.paid_at IS NOT NULL"
        else:
            # Seguridad primero: si no hay forma de validar pago, no devolvemos QRs/tickets.
            o_paid_pred = "1=0"

        # ownership: por auth_subject si existe, si no por buyer_email
        owner_predicates = []
        params = []
        if auth_subject and ("auth_subject" in orders_cols):
            owner_predicates.append("o.auth_subject = %s")
            params.append(auth_subject)
        if (email_sess or guest_email) and ("buyer_email" in orders_cols):
            owner_predicates.append("lower(o.buyer_email) = lower(%s)")
            params.append(email_sess or guest_email)

        if not owner_predicates:
            # guest: solo por last_order_id
            if allow_guest:
                owner_predicates.append("o.id = %s")
                params.append(order_id)
            else:
                return {"ok": True, "assets": []}

        where_owner = "(" + " OR ".join(owner_predicates) + ")"

        # filtro opcional: devolver solo una orden (mejor para pantalla de "Generando QR")
        filter_order = ""
        params2 = list(params)
        if order_id:
            filter_order = " AND o.id = %s"
            params2.append(order_id)

        sql = f"""
            SELECT
                t.id AS ticket_id,
                t.order_id,
                t.status,
                {t_ticket_type} AS ticket_type,
                {t_qr} AS qr_payload,
                t.created_at,
                o.event_slug,
                {e_title} AS event_title,
                {e_venue} AS venue,
                {e_city} AS city,
                {e_address} AS event_address,
                {e_date} AS event_date,
                {e_time} AS event_time,
                {o_buyer_name} AS buyer_name
            FROM tickets t
            JOIN orders o ON o.id = t.order_id
            LEFT JOIN events e ON e.slug = o.event_slug
            WHERE {where_owner}{filter_order} AND {o_paid_pred}
            ORDER BY t.created_at DESC
            LIMIT 500
        """
        cur.execute(sql, params2)
        rows = cur.fetchall() or []

        # ✅ Normalizar siempre a dict-like (evita KeyError: 0 cuando el cursor devuelve filas dict)
        data = _rows_to_dicts(cur, rows)

    assets = []
    for r in data:
        assets.append(
            {
                "ticket_id": r.get("ticket_id"),
                "order_id": r.get("order_id"),
                "status": r.get("status"),
                "ticket_type": r.get("ticket_type"),
                "qr_payload": r.get("qr_payload"),
                "created_at": _iso(r.get("created_at")),
                "event_slug": r.get("event_slug"),
                "event_title": r.get("event_title"),
                "venue": r.get("venue"),
                "city": r.get("city"),
                "event_address": r.get("event_address"),
                "event_date": r.get("event_date"),
                "event_time": r.get("event_time"),
                "buyer_name": r.get("buyer_name"),
            }
        )

    return {"ok": True, "assets": assets}
@router.get("/tickets.pdf")
def tickets_pdf(request: Request, tenant: str = Query("default"), ids: str = Query(""), email: str = Query("")):
    """Genera un PDF amigable de tickets, validando que pertenezcan al usuario."""
    user = (request.session or {}).get("user")
    guest_email = (email or "").strip().lower()

    if not user and not guest_email:
        raise HTTPException(status_code=401, detail="Not authenticated")

    ids_list = [i.strip() for i in (ids or "").split(",") if i.strip()]
    if not ids_list:
        raise HTTPException(status_code=400, detail="Missing ids")

    auth_subject = user.get("sub") if user else None
    email_sess = (user.get("email") or "").strip().lower() if user else None

    with _conn_cm(tenant) as conn:
        cur = conn.cursor()
        tickets_cols = set(_table_columns(cur, "tickets"))
        orders_cols = set(_table_columns(cur, "orders"))
        events_cols = set(_table_columns(cur, "events"))

        t_ticket_type = "t.ticket_type" if "ticket_type" in tickets_cols else "NULL::text"
        t_qr = "t.qr_payload" if "qr_payload" in tickets_cols else "t.qr_token"

        e_date = (
            "e.event_date" if "event_date" in events_cols else
            "e.date" if "date" in events_cols else
            "NULL::date"
        )
        e_time = (
            "e.event_time" if "event_time" in events_cols else
            "e.time" if "time" in events_cols else
            "NULL::text"
        )
        e_title = "e.title" if "title" in events_cols else "NULL::text"
        e_venue = "e.venue" if "venue" in events_cols else "NULL::text"
        e_city = "e.city" if "city" in events_cols else "NULL::text"
        e_address = "e.address" if "address" in events_cols else "NULL::text"
        o_buyer_name = "o.buyer_name" if "buyer_name" in orders_cols else "NULL::text"
        if "status" in orders_cols:
            o_paid_pred = "lower(COALESCE(o.status,'')) = 'paid'"
        elif "paid_at" in orders_cols:
            o_paid_pred = "o.paid_at IS NOT NULL"
        else:
            # Seguridad primero: si no hay forma de validar pago, no emitimos PDF de tickets.
            o_paid_pred = "1=0"
        o_buyer_email = "o.buyer_email" if "buyer_email" in orders_cols else "NULL::text"

        owner_predicates = []
        params = []
        if auth_subject and ("auth_subject" in orders_cols):
            owner_predicates.append("o.auth_subject = %s")
            params.append(auth_subject)
        if (email_sess or guest_email) and ("buyer_email" in orders_cols):
            owner_predicates.append("lower(o.buyer_email) = lower(%s)")
            params.append(email_sess or guest_email)

        if not owner_predicates:
            raise HTTPException(status_code=403, detail="Cannot validate ownership")

        where_owner = "(" + " OR ".join(owner_predicates) + ")"

        params_ids = params + [ids_list]
        sql = f"""
            SELECT
                t.id AS ticket_id,
                {t_ticket_type} AS ticket_type,
                {t_qr} AS qr_payload,
                o.event_slug,
                {e_title} AS event_title,
                {e_date} AS event_date,
                {e_time} AS event_time,
                {e_venue} AS venue,
                {e_city} AS city,
                {e_address} AS event_address,
                {o_buyer_name} AS buyer_name,
                {o_buyer_email} AS buyer_email
            FROM tickets t
            JOIN orders o ON o.id = t.order_id
            LEFT JOIN events e ON e.slug = o.event_slug
            WHERE {where_owner} AND {o_paid_pred}
              AND t.id = ANY(%s)
            ORDER BY t.created_at DESC
        """
        cur.execute(sql, params_ids)
        rows = _rows_to_dicts(cur, cur.fetchall() or [])

    if not rows:
        raise HTTPException(status_code=404, detail="No tickets found")

    logo_path = "static/favicon-192.png"

    def _fmt_date(v):
        if v is None:
            return ""
        try:
            return v.strftime("%d/%m/%Y")
        except Exception:
            return str(v)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    for idx, r in enumerate(rows, start=1):
        ticket_id = r.get("ticket_id")
        ticket_type = r.get("ticket_type")
        qr_payload = r.get("qr_payload") or str(ticket_id)
        event_title = r.get("event_title") or r.get("event_slug") or "Evento"
        event_date = _fmt_date(r.get("event_date"))
        event_time = str(r.get("event_time") or "").strip()
        venue = str(r.get("venue") or "").strip()
        city = str(r.get("city") or "").strip()
        event_address = str(r.get("event_address") or "").strip()
        buyer_name = str(r.get("buyer_name") or "").strip()
        buyer_email = str(r.get("buyer_email") or "").strip()

        c.setStrokeColorRGB(0.21, 0.25, 0.33)
        c.roundRect(28, 28, width - 56, height - 56, 18, stroke=1, fill=0)

        if os.path.exists(logo_path):
            c.drawImage(ImageReader(logo_path), 40, height - 88, width=36, height=36, mask='auto')
        c.setFont("Helvetica-Bold", 18)
        c.drawString(84, height - 64, "TicketPro")
        c.setFont("Helvetica", 10)
        c.drawString(84, height - 80, "Entrada confirmada")

        c.setFont("Helvetica-Bold", 13)
        c.drawString(40, height - 120, event_title)
        c.setFont("Helvetica", 10)
        c.drawString(40, height - 138, f"Ticket #{idx} · ID: {ticket_id}")

        y = height - 170
        for label, value in [
            ("Titular", buyer_name or "-"),
            ("Email", buyer_email or "-"),
            ("Tipo", ticket_type or "General"),
            ("Fecha", event_date or "-"),
            ("Hora", event_time or "-"),
            ("Lugar", venue or "-"),
            ("Dirección", event_address or "-"),
            ("Ciudad", city or "-"),
        ]:
            c.setFont("Helvetica-Bold", 9)
            c.drawString(40, y, f"{label}:")
            c.setFont("Helvetica", 9)
            c.drawString(108, y, value)
            y -= 16

        qr_img = qrcode.make(qr_payload)
        img_buf = io.BytesIO()
        qr_img.save(img_buf, format="PNG")
        img_buf.seek(0)
        qr_reader = ImageReader(img_buf)
        c.drawImage(qr_reader, width - 220, height - 355, width=170, height=170, mask='auto')

        c.setFont("Helvetica", 8)
        c.drawString(40, 50, "Mostrá este QR en el ingreso. También podés validar con el Ticket ID.")
        c.showPage()

    c.save()
    pdf_bytes = buf.getvalue()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=tickets.pdf"},
    )

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

    requester_email = str(user.get("email") or "").strip().lower()
    requester_sub = str(user.get("sub") or "").strip()
    reason = (payload.reason or "").strip()

    with _conn_cm(tenant_id) as conn:
        cur = conn.cursor()
        ocols = _table_columns(cur, "orders")
        tcols = _table_columns(cur, "tickets")
        ecols = _table_columns(cur, "events")

        owner_predicates = []
        owner_params: list[Any] = []
        if requester_sub and "auth_subject" in ocols:
            owner_predicates.append("o.auth_subject = %s")
            owner_params.append(requester_sub)
        if requester_email and "buyer_email" in ocols:
            owner_predicates.append("lower(o.buyer_email) = lower(%s)")
            owner_params.append(requester_email)
        if not owner_predicates:
            raise HTTPException(status_code=403, detail="cannot_validate_ownership")

        where_owner = "(" + " OR ".join(owner_predicates) + ")"
        e_title = "e.title" if "title" in ecols else "NULL::text"
        e_venue = "e.venue" if "venue" in ecols else "NULL::text"
        e_city = "e.city" if "city" in ecols else "NULL::text"
        e_address = "e.address" if "address" in ecols else "NULL::text"
        e_date = "e.event_date" if "event_date" in ecols else ("e.date" if "date" in ecols else "NULL::text")
        e_time = "e.event_time" if "event_time" in ecols else ("e.time" if "time" in ecols else "NULL::text")
        o_buyer_name = "COALESCE(o.buyer_name, '')" if "buyer_name" in ocols else "''"
        o_buyer_email = "COALESCE(o.buyer_email, '')" if "buyer_email" in ocols else "''"
        o_buyer_phone = "COALESCE(o.buyer_phone, '')" if "buyer_phone" in ocols else "''"

        params = [tenant_id, payload.order_id, *owner_params]
        cur.execute(
            f"""
            SELECT
                o.id AS order_id,
                o.event_slug,
                {e_title} AS event_title,
                {e_venue} AS venue,
                {e_city} AS city,
                {e_address} AS event_address,
                {e_date} AS event_date,
                {e_time} AS event_time,
                {o_buyer_name} AS buyer_name,
                {o_buyer_email} AS buyer_email,
                {o_buyer_phone} AS buyer_phone
            FROM orders o
            LEFT JOIN events e ON e.slug = o.event_slug
            WHERE o.tenant_id = %s
              AND o.id = %s
              AND {where_owner}
            LIMIT 1
            """,
            tuple(params),
        )
        order_row = _rows_to_dicts(cur, cur.fetchall() or [])
        if not order_row:
            raise HTTPException(status_code=404, detail="order_not_found")
        order = order_row[0]

        ticket_rows = []
        if "order_id" in tcols:
            ticket_cols = ["t.id AS ticket_id", "t.status"]
            if "ticket_type" in tcols:
                ticket_cols.append("t.ticket_type")
            else:
                ticket_cols.append("NULL::text AS ticket_type")

            ticket_sql = f"SELECT {', '.join(ticket_cols)} FROM tickets t WHERE t.order_id=%s"
            ticket_params: list[Any] = [payload.order_id]
            if payload.id:
                ticket_sql += " AND t.id=%s"
                ticket_params.append(payload.id)
            ticket_sql += " ORDER BY t.created_at DESC NULLS LAST, t.id DESC"
            cur.execute(ticket_sql, tuple(ticket_params))
            ticket_rows = _rows_to_dicts(cur, cur.fetchall() or [])

        if payload.id and not ticket_rows:
            raise HTTPException(status_code=404, detail="ticket_not_found")

        if "status" in tcols and ticket_rows:
            ids_to_mark = [str(t.get("ticket_id")) for t in ticket_rows if t.get("ticket_id")]
            if ids_to_mark:
                cur.execute(
                    "UPDATE tickets SET status='cancel_requested' WHERE id = ANY(%s)",
                    (ids_to_mark,),
                )
                conn.commit()

        # Importante: NO cancelamos automáticamente la orden/tickets.
        # Este endpoint solo notifica a soporte para revisión manual.

    support_to = "soporte@ticketpro.com.ar"
    event_title = order.get("event_title") or order.get("event_slug") or "(sin evento)"
    ticket_lines = []
    for t in ticket_rows:
        ticket_lines.append(f"- {t.get('ticket_id')} ({t.get('ticket_type') or 'General'})")
    tickets_block = "\n".join(ticket_lines) if ticket_lines else "- (sin tickets encontrados)"

    subject = f"[Arrepentimiento] Orden {payload.order_id} · {event_title}"
    text = (
        "Se recibió una solicitud de arrepentimiento.\n\n"
        f"Orden: {payload.order_id}\n"
        f"Evento: {event_title}\n"
        f"Fecha/Hora: {order.get('event_date') or '-'} {order.get('event_time') or ''}\n"
        f"Lugar: {order.get('venue') or '-'}\n"
        f"Dirección: {order.get('event_address') or '-'}\n"
        f"Ciudad: {order.get('city') or '-'}\n\n"
        f"Titular: {order.get('buyer_name') or '-'}\n"
        f"Email contacto: {order.get('buyer_email') or requester_email or '-'}\n"
        f"Teléfono contacto: {order.get('buyer_phone') or '-'}\n\n"
        f"Kind: {payload.kind or 'entrada'}\n"
        f"Ticket solicitado: {payload.id or '(todos de la orden)'}\n"
        f"Motivo: {reason or '(sin motivo)'}\n\n"
        f"Tickets:\n{tickets_block}\n"
    )

    html = f"""
    <div style="font-family:Arial,sans-serif; line-height:1.5; color:#111;">
      <h2>Solicitud de arrepentimiento</h2>
      <p><strong>Orden:</strong> {payload.order_id}</p>
      <p><strong>Evento:</strong> {event_title}</p>
      <p><strong>Fecha / Hora:</strong> {order.get('event_date') or '-'} {order.get('event_time') or ''}</p>
      <p><strong>Lugar:</strong> {order.get('venue') or '-'} · <strong>Dirección:</strong> {order.get('event_address') or '-'} · <strong>Ciudad:</strong> {order.get('city') or '-'}</p>
      <hr/>
      <p><strong>Titular:</strong> {order.get('buyer_name') or '-'}</p>
      <p><strong>Email contacto:</strong> {order.get('buyer_email') or requester_email or '-'}</p>
      <p><strong>Teléfono contacto:</strong> {order.get('buyer_phone') or '-'}</p>
      <p><strong>Ticket:</strong> {payload.id or '(todos de la orden)'}</p>
      <p><strong>Motivo:</strong> {reason or '(sin motivo)'}</p>
      <p><strong>Detalle tickets:</strong><br/>{'<br/>'.join(ticket_lines) if ticket_lines else '- (sin tickets encontrados)'}</p>
    </div>
    """

    try:
        send_email(to_email=support_to, subject=subject, text=text, html=html)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"no_se_pudo_enviar_mail_soporte: {e}")

    return {
        "ok": True,
        "notified": True,
        "to": support_to,
        "message": "Solicitud enviada a soporte para evaluación. No se canceló automáticamente.",
    }


@router.post("/transfer-order")
def transfer_order(
    request: Request,
    payload: TransferOrderIn,
    tenant_id: str = Query(default="default", alias="tenant"),
):
    tenant_id = _norm_tenant_id(tenant_id)

    user = getattr(request, "session", {}).get("user")
    if not user:
        raise HTTPException(status_code=401, detail="not_authenticated")

    from_email = str((user or {}).get("email") or "").strip().lower()
    auth_subject = str((user or {}).get("sub") or (user or {}).get("auth_subject") or "").strip()
    to_email = (payload.to_email or "").strip().lower()
    ticket_id = str(payload.ticket_id or "").strip()
    if not to_email or "@" not in to_email:
        raise HTTPException(status_code=400, detail="invalid_to_email")

    transfer_context: Dict[str, str] = {
        "event_slug": "",
        "buyer_name": "",
    }

    with _conn_cm(tenant_id) as conn:
        cur = conn.cursor()
        ocols = _table_columns(cur, "orders")
        tcols = _table_columns(cur, "tickets")

        owner_pred = []
        owner_params: list[Any] = []
        if auth_subject and ("auth_subject" in ocols):
            owner_pred.append("auth_subject = %s")
            owner_params.append(auth_subject)
        if from_email and ("buyer_email" in ocols):
            owner_pred.append("lower(buyer_email)=lower(%s)")
            owner_params.append(from_email)

        if not owner_pred:
            raise HTTPException(status_code=403, detail="order_transfer_forbidden")

        cur.execute(
            f"SELECT id FROM orders WHERE tenant_id=%s AND id=%s AND ({' OR '.join(owner_pred)}) LIMIT 1",
            (tenant_id, payload.order_id, *owner_params),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="order_not_found")

        order_detail_cols = [c for c in ("event_slug", "buyer_name") if c in ocols]
        if order_detail_cols:
            cur.execute(
                f"SELECT {', '.join(order_detail_cols)} FROM orders WHERE tenant_id=%s AND id=%s LIMIT 1",
                (tenant_id, payload.order_id),
            )
            row = cur.fetchone()
            if row:
                for idx, col in enumerate(order_detail_cols):
                    if isinstance(row, dict):
                        transfer_context[col] = str(row.get(col) or "").strip()
                    else:
                        transfer_context[col] = str(row[idx] or "").strip()

        transferred_ticket = False
        if ticket_id and "order_id" in tcols:
            cur.execute(
                "SELECT id FROM tickets WHERE id=%s AND order_id=%s LIMIT 1",
                (ticket_id, payload.order_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="ticket_not_found")

            cur.execute("SELECT COUNT(*) FROM tickets WHERE order_id=%s", (payload.order_id,))
            row_count = cur.fetchone()
            total_in_order = int((row_count.get("count") if isinstance(row_count, dict) else row_count[0]) or 0)

            if total_in_order > 1:
                new_order_id = str(uuid.uuid4())
                insert_cols = ["id"]
                select_expr = ["%s"]
                insert_params: list[Any] = [new_order_id]

                for col in ocols:
                    if col == "id":
                        continue
                    insert_cols.append(col)
                    if col == "buyer_email":
                        select_expr.append("%s")
                        insert_params.append(to_email)
                    elif col == "auth_subject":
                        select_expr.append("NULL")
                    else:
                        select_expr.append(f"o.{col}")

                cur.execute(
                    f"""
                    INSERT INTO orders ({', '.join(insert_cols)})
                    SELECT {', '.join(select_expr)}
                    FROM orders o
                    WHERE o.tenant_id=%s AND o.id=%s
                    LIMIT 1
                    """,
                    tuple(insert_params + [tenant_id, payload.order_id]),
                )

                cur.execute(
                    "UPDATE tickets SET order_id=%s WHERE id=%s AND order_id=%s",
                    (new_order_id, ticket_id, payload.order_id),
                )
                transferred_ticket = True

        if not transferred_ticket:
            sets = ["buyer_email=%s"]
            params_upd: list[Any] = [to_email]
            if "auth_subject" in ocols:
                sets.append("auth_subject=NULL")
            cur.execute(
                f"UPDATE orders SET {', '.join(sets)} WHERE tenant_id=%s AND id=%s",
                tuple(params_upd + [tenant_id, payload.order_id]),
            )

        conn.commit()

    mail_notified = True
    mail_warning = None
    try:
        _send_transfer_notification_email(
            to_email=to_email,
            from_email=from_email,
            order_id=payload.order_id,
            event_slug=transfer_context.get("event_slug") or "",
            ticket_id=ticket_id,
        )
    except Exception as e:
        mail_notified = False
        mail_warning = str(e)

    return {
        "ok": True,
        "ticket_transfer": transferred_ticket,
        "mail_notified": mail_notified,
        **({"mail_warning": mail_warning} if mail_warning else {}),
    }


# -------------------------
# PRO: validar/consumir QR (scanner)
# -------------------------
class QRValidateIn(BaseModel):
    qr_token: str
    event_slug: Optional[str] = None
    staff_token: Optional[str] = None


def _extract_qr_token(raw_value: str) -> str:
    raw = str(raw_value or "").strip()
    if not raw:
        return ""

    if ":" in raw and raw.upper().startswith("TICKETPRO:"):
        parts = [p for p in raw.split(":") if p]
        if parts:
            raw = parts[-1].strip()

    if "qr_token=" in raw:
        try:
            from urllib.parse import parse_qs, urlparse

            parsed = urlparse(raw)
            token_qs = parse_qs(parsed.query or "").get("qr_token") or []
            if token_qs:
                raw = str(token_qs[0] or "").strip()
        except Exception:
            pass

    return raw


@router.post("/validate")
def validate_qr(
    payload: QRValidateIn,
    request: Request,
    tenant_id: str = Query(default="default", alias="tenant"),
):
    """
    Valida y marca como 'used' un ticket por qr_token.
    Si ya estaba usado, devuelve valid=false.
    """
    qr_token = _extract_qr_token(payload.qr_token)
    requested_event_slug = str(payload.event_slug or "").strip()
    tenant_id = _norm_tenant_id(tenant_id)

    if not qr_token:
        raise HTTPException(status_code=400, detail="missing_qr_token")

    with _conn_cm(tenant_id) as conn:
        cur = conn.cursor()

        tcols = _table_columns(cur, "tickets")
        needed = {"id", "qr_token", "status"}
        missing = [c for c in needed if c not in tcols]
        if missing:
            raise HTTPException(status_code=500, detail=f"Schema inválido tickets faltan: {missing}")

        where_parts = ["(qr_token = %s"]
        params: list[Any] = [qr_token]
        if "qr_payload" in tcols:
            where_parts.append("qr_payload = %s")
            params.append(qr_token)
        where_parts[-1] = where_parts[-1] + ")"
        if "tenant_id" in tcols:
            where_parts.append("tenant_id = %s")
            params.append(tenant_id)

        cur.execute(
            f"""
            SELECT id, status, event_slug, sale_item_id, order_id
            FROM tickets
            WHERE {' AND '.join(where_parts)}
            LIMIT 1
            """,
            tuple(params),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="ticket_not_found")

        if isinstance(row, dict):
            ticket_id = row["id"]
            status = row["status"]
            row_event_slug = str(row.get("event_slug") or "").strip()
            sale_item_id = row.get("sale_item_id")
            order_id = row.get("order_id")
        else:
            ticket_id, status, row_event_slug, sale_item_id, order_id = row
            row_event_slug = str(row_event_slug or "").strip()

        effective_event_slug = requested_event_slug or row_event_slug
        if payload.staff_token or request.headers.get("x-staff-token") or request.query_params.get("token"):
            require_staff_token_for_event(
                request,
                event_slug=effective_event_slug,
                scope="validate",
                token=payload.staff_token,
            )

        if requested_event_slug and row_event_slug and row_event_slug != requested_event_slug:
            return {
                "ok": True,
                "valid": False,
                "reason": "event_mismatch",
                "ticket_id": str(ticket_id),
                "event_slug": row_event_slug,
            }

        normalized_status = str(status or "").strip().lower()
        valid_statuses = {"valid", "active"}

        if normalized_status not in valid_statuses:
            return {
                "ok": True,
                "valid": False,
                "reason": f"status_{status}",
                "ticket_id": str(ticket_id),
                "event_slug": row_event_slug,
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
        "event_slug": row_event_slug,
        "sale_item_id": sale_item_id,
        "order_id": str(order_id) if order_id else None,
    }
