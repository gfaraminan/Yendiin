from __future__ import annotations

import json
import time
import uuid
import io

import qrcode
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.db import get_conn as db_get_conn

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

        with _conn_cm() as conn:
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
def my_assets(request: Request, tenant: str = Query("default")):
    """Devuelve los tickets/entradas del usuario logueado (sin filtrar por productor).

    Frontend esperado: { ok: true, assets: [...] }
    """
    user = (request.session or {}).get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    auth_subject = user.get("sub")
    email = user.get("email")
    email_sess = (email or "").strip().lower() if email else None
    guest_email = None
    try:
        guest_email = request.session.get("guest_email") if getattr(request, "session", None) else None
    except Exception:
        guest_email = None
    guest_email = guest_email.strip().lower() if isinstance(guest_email, str) else None

    with _conn_cm(tenant) as conn:
        cur = conn.cursor()

        tickets_cols = set(_table_columns(cur, "tickets"))
        orders_cols = set(_table_columns(cur, "orders"))
        events_cols = set(_table_columns(cur, "events"))

        # campos opcionales por compatibilidad de schema
        t_ticket_type = "t.ticket_type" if "ticket_type" in tickets_cols else "NULL::text"
        t_qr = "t.qr_payload" if "qr_payload" in tickets_cols else "t.id::text"

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
        e_title = "e.title" if "title" in events_cols else "NULL::text"

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
            # no tenemos ninguna forma segura de asociar pedidos al usuario
            return {"ok": True, "assets": []}

        where_owner = "(" + " OR ".join(owner_predicates) + ")"

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
                {e_date} AS event_date,
                {e_time} AS event_time
            FROM tickets t
            JOIN orders o ON o.id = t.order_id
            LEFT JOIN events e ON e.slug = o.event_slug
            WHERE {where_owner} AND lower(o.status) = 'paid'
            ORDER BY t.created_at DESC
            LIMIT 500
        """
        cur.execute(sql, params)
        rows = cur.fetchall() or []

        # ✅ Normalizar siempre a dict-like (evita KeyError: 0 cuando el cursor devuelve filas dict)
        data = _rows_to_dicts(cur, rows)

    assets = []
    for r in data:
        assets.append(
            {
                "ticket_id": str(r.get("ticket_id")),
                "order_id": str(r.get("order_id")) if r.get("order_id") is not None else None,
                "status": r.get("status"),
                "ticket_type": r.get("ticket_type"),
                "qr_payload": r.get("qr_payload"),
                "created_at": (
                    r["created_at"].isoformat()
                    if getattr(r.get("created_at"), "isoformat", None)
                    else r.get("created_at")
                ),
                "event_slug": r.get("event_slug"),
                "event_title": r.get("event_title"),
                "venue": r.get("venue"),
                "city": r.get("city"),
                "event_date": r.get("event_date"),
                "event_time": r.get("event_time"),
            }
        )

    return {"ok": True, "assets": assets}
@router.get("/tickets.pdf")
def tickets_pdf(
    request: Request,
    tenant: str = Query("default"),
    ids: str = Query(""),
    email: str = Query(""),
    deliver: int = Query(0),
    to: str = Query(""),
):
    """Genera un PDF con los tickets solicitados (por IDs), validando que pertenezcan al usuario."""
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

        t_ticket_type = "t.ticket_type" if "ticket_type" in tickets_cols else "NULL::text AS ticket_type"
        t_qr = "t.qr_payload" if "qr_payload" in tickets_cols else "t.id::text AS qr_payload"

        e_date = (
            "e.event_date" if "event_date" in events_cols else
            "e.date" if "date" in events_cols else
            "NULL::text AS event_date"
        )
        e_time = (
            "e.event_time" if "event_time" in events_cols else
            "e.time" if "time" in events_cols else
            "NULL::text AS event_time"
        )
        e_title = "e.title" if "title" in events_cols else "NULL::text AS title"

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

        # psycopg ANY espera lista/tuple
        params_ids = params + [ids_list]

        sql = f"""
            SELECT
                t.id AS ticket_id,
                {t_ticket_type},
                {t_qr} AS qr_payload,
                o.event_slug,
                {e_title} AS event_title,
                {e_date} AS event_date,
                {e_time} AS event_time
            FROM tickets t
            JOIN orders o ON o.id = t.order_id
            LEFT JOIN events e ON e.slug = o.event_slug
            WHERE {where_owner} AND lower(o.status) = 'paid'
              AND t.id = ANY(%s)
            ORDER BY t.created_at DESC
        """
        cur.execute(sql, params_ids)
        rows = cur.fetchall() or []

    if not rows:
        raise HTTPException(status_code=404, detail="No tickets found")

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    for (ticket_id, ticket_type, qr_payload, event_slug, event_title, event_date, event_time) in rows:
        # Header
        c.setFont("Helvetica-Bold", 18)
        c.drawString(40, height - 50, "TICKETPRO")
        c.setFont("Helvetica", 11)
        c.drawString(40, height - 70, f"Evento: {event_title or event_slug}")
        if event_date or event_time:
            c.drawString(40, height - 86, f"Fecha/Hora: {(event_date or '')} {(event_time or '')}".strip())
        if ticket_type:
            c.drawString(40, height - 102, f"Tipo: {ticket_type}")
        c.drawString(40, height - 118, f"Ticket ID: {ticket_id}")

        # QR
        qr_text = (qr_payload or str(ticket_id))
        qr_img = qrcode.make(qr_text)
        img_buf = io.BytesIO()
        qr_img.save(img_buf, format="PNG")
        img_buf.seek(0)
        qr_reader = ImageReader(img_buf)

        qr_size = 260
        c.drawImage(qr_reader, 40, height - 420, width=qr_size, height=qr_size, mask='auto')

        c.setFont("Helvetica", 9)
        c.drawString(40, 40, "Mostrá este QR en el ingreso. Si hay problema, este Ticket ID también valida.")

        c.showPage()

    c.save()
    pdf_bytes = buf.getvalue()

    # Si deliver=1, enviamos el PDF por mail (sin romper el flujo de descarga).
    # Seguridad: solo permitimos enviar al mail del usuario autenticado o al "email" pasado (modo invitado).
    if int(deliver or 0) == 1:
        sess_email = (user.get("email") or "").strip().lower() if isinstance(user, dict) else ""
        guest_email = (email or "").strip().lower()
        requested = (to or "").strip().lower()
        recipient = requested or sess_email or guest_email

        if not recipient:
            raise HTTPException(status_code=400, detail="No hay email destino para enviar los tickets.")

        allowed = {e for e in [sess_email, guest_email] if e}
        if allowed and recipient not in allowed:
            raise HTTPException(status_code=403, detail="Email destino no autorizado.")

        subject = "Tus entradas / QR - TicketPro"
        html = (
            "<p>¡Pago confirmado! 👇</p>"
            "<p>Te adjuntamos un PDF con tus entradas y QR.</p>"
            "<p>Guardalo en el celu y listo.</p>"
        )

        send_email(
            to=recipient,
            subject=subject,
            html=html,
            attachments=[("tickets.pdf", pdf_bytes, "application/pdf")],
        )
        return {"ok": True, "sent_to": recipient, "count": len(tickets)}

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=tickets.pdf"},
    )

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

    with _conn_cm() as conn:
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

    with _conn_cm() as conn:
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
