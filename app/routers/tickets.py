from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
import os
import io
import qrcode
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from app.db import get_conn as db_get_conn

router = APIRouter()

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/var/data/uploads")
os.makedirs(f"{UPLOAD_DIR}/tickets", exist_ok=True)


def _table_columns(cur, table: str) -> set[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s
        """,
        (table,),
    )
    rows = cur.fetchall() or []
    out = set()
    for r in rows:
        if isinstance(r, dict):
            out.add(str(r.get("column_name") or ""))
        elif r:
            out.add(str(r[0]))
    return {c for c in out if c}


def _extract_buyer_name_from_items(items: object) -> str:
    if not isinstance(items, list):
        return ""
    for it in items:
        if not isinstance(it, dict):
            continue
        for k in ("buyer_name", "full_name", "name", "holder_name"):
            v = str(it.get(k) or "").strip()
            if v:
                return v
    return ""

@router.get("/api/tickets/{ticket_id}/pdf")
def download_ticket_pdf(ticket_id: str):
    pdf_path = f"{UPLOAD_DIR}/tickets/{ticket_id}.pdf"

    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF no encontrado")

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"ticket-{ticket_id}.pdf"
    )

@router.get("/api/tickets/orders/{order_id}/pdf")
def download_order_pdf(order_id: str):
    # payments_mp stores PDFs as order-<order_id>.pdf
    pdf_path = f"{UPLOAD_DIR}/tickets/order-{order_id}.pdf"

    # Regenerar siempre desde DB para evitar servir PDFs viejos sin metadata.
    try:
            with db_get_conn() as conn:
                cur = conn.cursor()
                tcols = _table_columns(cur, "tickets")
                ocols = _table_columns(cur, "orders")
                ecols = _table_columns(cur, "events")

                t_qr = (
                    "t.qr_payload" if "qr_payload" in tcols else
                    "t.qr_token" if "qr_token" in tcols else
                    "t.id::text"
                )
                t_type = (
                    "t.ticket_type" if "ticket_type" in tcols else
                    "t.type" if "type" in tcols else
                    "'General'::text"
                )
                e_title = "e.title" if "title" in ecols else "o.event_slug"
                e_date = (
                    "e.event_date::text" if "event_date" in ecols else
                    "e.date::text" if "date" in ecols else
                    "e.date_text::text" if "date_text" in ecols else
                    "'-'::text"
                )
                e_time = (
                    "e.event_time::text" if "event_time" in ecols else
                    "e.time::text" if "time" in ecols else
                    "'-'::text"
                )
                e_venue = "e.venue" if "venue" in ecols else "'-'::text"
                e_city = "e.city" if "city" in ecols else "'-'::text"
                e_addr = "e.address" if "address" in ecols else "'-'::text"
                o_buyer_name = "o.buyer_name" if "buyer_name" in ocols else "'-'::text"
                o_buyer_email = "o.buyer_email" if "buyer_email" in ocols else ("o.customer_label" if "customer_label" in ocols else "'-'::text")
                o_date = "o.date_text" if "date_text" in ocols else "'-'::text"
                o_venue = "o.venue" if "venue" in ocols else "'-'::text"
                o_city = "o.city" if "city" in ocols else "'-'::text"
                o_addr = "o.event_address" if "event_address" in ocols else ("o.address" if "address" in ocols else "'-'::text")
                cur.execute(
                    f"""
                    SELECT
                        t.id AS ticket_id,
                        COALESCE({t_qr}, t.id::text) AS qr_payload,
                        COALESCE({t_type}, 'General') AS ticket_type,
                        o.event_slug,
                        COALESCE({e_title}, o.event_slug, 'Evento') AS event_title,
                        COALESCE({e_date}, {o_date}, '-') AS event_date,
                        COALESCE({e_time}, '-') AS event_time,
                        COALESCE({e_venue}, {o_venue}, '-') AS venue,
                        COALESCE({e_city}, {o_city}, '-') AS city,
                        COALESCE({e_addr}, {o_addr}, '-') AS event_address,
                        COALESCE({o_buyer_name}, '-') AS buyer_name,
                        COALESCE({o_buyer_email}, '-') AS buyer_email
                    FROM tickets t
                    JOIN orders o ON o.id = t.order_id
                    LEFT JOIN events e ON e.slug = o.event_slug
                    WHERE t.order_id = %s
                    ORDER BY t.created_at DESC
                    """,
                    (order_id,),
                )
                rows = cur.fetchall() or []
                if not rows:
                    # Fallback final: reconstruir desde orders.items_json cuando aún no hay filas en tickets.
                    o_buyer_email2 = "o.buyer_email" if "buyer_email" in ocols else ("o.customer_label" if "customer_label" in ocols else "'-'::text")
                    o_buyer_name2 = "o.buyer_name" if "buyer_name" in ocols else "'-'::text"
                    o_date2 = "o.date_text" if "date_text" in ocols else "'-'::text"
                    o_venue2 = "o.venue" if "venue" in ocols else "'-'::text"
                    o_city2 = "o.city" if "city" in ocols else "'-'::text"
                    o_addr2 = "o.event_address" if "event_address" in ocols else ("o.address" if "address" in ocols else "'-'::text")
                    cur.execute(
                        """
                        SELECT o.id AS order_id, o.event_slug, o.items_json,
                               COALESCE({o_buyer_name2}, '-') AS buyer_name,
                               COALESCE({o_buyer_email2}, '-') AS buyer_email,
                               COALESCE({o_date2}, '-') AS order_date_text,
                               COALESCE({o_venue2}, '-') AS order_venue,
                               COALESCE({o_city2}, '-') AS order_city,
                               COALESCE({o_addr2}, '-') AS order_address
                        FROM orders o
                        WHERE o.id=%s
                        LIMIT 1
                        """.format(
                            o_buyer_name2=o_buyer_name2,
                            o_buyer_email2=o_buyer_email2,
                            o_date2=o_date2,
                            o_venue2=o_venue2,
                            o_city2=o_city2,
                            o_addr2=o_addr2,
                        ),
                        (order_id,),
                    )
                    o = cur.fetchone()
                    if not o:
                        raise HTTPException(status_code=404, detail="PDF no encontrado")
                    if not isinstance(o, dict):
                        cols = [d[0] for d in (cur.description or [])]
                        o = dict(zip(cols, o))
                    import json
                    items_raw = o.get("items_json")
                    try:
                        items = json.loads(items_raw) if isinstance(items_raw, str) else (items_raw or [])
                    except Exception:
                        items = []
                    if not isinstance(items, list) or not items:
                        raise HTTPException(status_code=404, detail="PDF no encontrado")

                    # enriquecer con metadata del evento cargada por productor
                    event_slug = str(o.get("event_slug") or "").strip()
                    event_meta = {
                        "event_title": event_slug or "Evento",
                        "event_date": "-",
                        "event_time": "-",
                        "venue": "-",
                        "city": "-",
                        "event_address": "-",
                    }
                    if event_slug:
                        e_title2 = "title" if "title" in ecols else "slug"
                        e_date2 = "event_date::text" if "event_date" in ecols else ("date::text" if "date" in ecols else ("date_text::text" if "date_text" in ecols else "'-'::text"))
                        e_time2 = "event_time::text" if "event_time" in ecols else ("time::text" if "time" in ecols else "'-'::text")
                        e_venue2 = "venue" if "venue" in ecols else "'-'::text"
                        e_city2 = "city" if "city" in ecols else "'-'::text"
                        e_addr2 = "address" if "address" in ecols else "'-'::text"
                        cur.execute(
                            f"""
                            SELECT COALESCE({e_title2}, %s) AS event_title,
                                   COALESCE({e_date2}, '-') AS event_date,
                                   COALESCE({e_time2}, '-') AS event_time,
                                   COALESCE({e_venue2}, '-') AS venue,
                                   COALESCE({e_city2}, '-') AS city,
                                   COALESCE({e_addr2}, '-') AS event_address
                            FROM events
                            WHERE slug=%s
                            LIMIT 1
                            """,
                            (event_slug, event_slug),
                        )
                        em = cur.fetchone()
                        if em:
                            if not isinstance(em, dict):
                                cols = [d[0] for d in (cur.description or [])]
                                em = dict(zip(cols, em))
                            event_meta.update({k: em.get(k) for k in event_meta.keys()})

                    buyer_name_from_items = _extract_buyer_name_from_items(items)
                    rows = []
                    seq = 0
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        qty = int(it.get("qty") or it.get("quantity") or 1)
                        for _ in range(max(0, qty)):
                            seq += 1
                            rows.append(
                                {
                                    "ticket_id": f"virtual-{order_id}-{seq}",
                                    "qr_payload": f"ORD:{order_id}:{seq}",
                                    "ticket_type": it.get("name") or it.get("ticket_type") or it.get("type") or "General",
                                    "event_slug": event_slug,
                                    "event_title": event_meta.get("event_title"),
                                    "event_date": event_meta.get("event_date") or o.get("order_date_text"),
                                    "event_time": event_meta.get("event_time"),
                                    "venue": event_meta.get("venue") if str(event_meta.get("venue") or "").strip() not in {"", "-"} else o.get("order_venue"),
                                    "city": event_meta.get("city") if str(event_meta.get("city") or "").strip() not in {"", "-"} else o.get("order_city"),
                                    "event_address": event_meta.get("event_address") if str(event_meta.get("event_address") or "").strip() not in {"", "-"} else o.get("order_address"),
                                    "buyer_name": o.get("buyer_name") or buyer_name_from_items or "-",
                                    "buyer_email": o.get("buyer_email") or "-",
                                }
                            )

                # tuple/dict compatibility
                if not isinstance(rows[0], dict):
                    cols = [d[0] for d in (cur.description or [])]
                    rows = [dict(zip(cols, r)) for r in rows]

            from app.ticket_pdf import build_tickets_pdf

            pdf_bytes = build_tickets_pdf(rows)

            # Persistimos para siguientes descargas.
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)
            return Response(content=pdf_bytes, media_type="application/pdf")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="PDF no encontrado")
