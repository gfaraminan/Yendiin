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

    if not os.path.exists(pdf_path):
        # Fallback: reconstruir PDF on-demand desde DB para no depender solo del archivo persistido.
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
                cur.execute(
                    f"""
                    SELECT
                        t.id AS ticket_id,
                        COALESCE({t_qr}, t.id::text) AS qr_payload,
                        o.event_slug,
                        COALESCE({e_title}, o.event_slug, 'Evento') AS event_title,
                        COALESCE({e_date}, '-') AS event_date,
                        COALESCE({e_time}, '-') AS event_time,
                        COALESCE({e_venue}, '-') AS venue,
                        COALESCE({e_city}, '-') AS city,
                        COALESCE({e_addr}, '-') AS event_address,
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
                    raise HTTPException(status_code=404, detail="PDF no encontrado")

                # tuple/dict compatibility
                if not isinstance(rows[0], dict):
                    cols = [d[0] for d in (cur.description or [])]
                    rows = [dict(zip(cols, r)) for r in rows]

            buf = io.BytesIO()
            c = canvas.Canvas(buf, pagesize=A4)
            width, height = A4
            for idx, r in enumerate(rows, start=1):
                c.setFont("Helvetica-Bold", 16)
                c.drawString(40, height - 60, "Yendiin · Ticket")
                c.setFont("Helvetica-Bold", 13)
                c.drawString(40, height - 95, str(r.get("event_title") or "Evento"))
                c.setFont("Helvetica", 10)
                c.drawString(40, height - 115, f"Ticket {idx}/{len(rows)} · ID: {r.get('ticket_id')}")
                c.drawString(40, height - 140, f"Titular: {r.get('buyer_name') or '-'}")
                c.drawString(40, height - 156, f"Email: {r.get('buyer_email') or '-'}")
                c.drawString(40, height - 172, f"Fecha/Hora: {r.get('event_date') or '-'} {r.get('event_time') or '-'}")
                c.drawString(40, height - 188, f"Lugar: {r.get('venue') or '-'} · {r.get('city') or '-'}")
                c.drawString(40, height - 204, f"Dirección: {r.get('event_address') or '-'}")

                qr_img = qrcode.make(str(r.get("qr_payload") or r.get("ticket_id") or ""))
                img_buf = io.BytesIO()
                qr_img.save(img_buf, format="PNG")
                img_buf.seek(0)
                c.drawImage(ImageReader(img_buf), width - 220, height - 300, width=170, height=170, mask="auto")
                c.showPage()
            c.save()
            pdf_bytes = buf.getvalue()

            # Persistimos para siguientes descargas.
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)
            return Response(content=pdf_bytes, media_type="application/pdf")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=404, detail="PDF no encontrado")

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"order-{order_id}.pdf"
    )
