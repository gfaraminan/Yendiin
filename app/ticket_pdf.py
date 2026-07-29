"""Shared, branded PDF renderer for tickets sent and downloaded by customers."""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any, Iterable

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


NAVY = (15 / 255, 23 / 255, 42 / 255)
PURPLE = (124 / 255, 58 / 255, 237 / 255)
PINK = (236 / 255, 72 / 255, 153 / 255)
SLATE = (71 / 255, 85 / 255, 105 / 255)
LIGHT = (248 / 255, 250 / 255, 252 / 255)


def _text(value: Any, fallback: str = "-") -> str:
    result = str(value or "").strip()
    return result or fallback


def _date(value: Any) -> str:
    try:
        return value.strftime("%d/%m/%Y")
    except (AttributeError, ValueError):
        return _text(value)


def _fit(value: Any, font: str, size: float, max_width: float) -> str:
    """Truncate long database values instead of letting them overlap the QR."""
    result = _text(value)
    if stringWidth(result, font, size) <= max_width:
        return result
    suffix = "..."
    while result and stringWidth(result + suffix, font, size) > max_width:
        result = result[:-1]
    return result + suffix


def _logo_path() -> Path | None:
    configured = os.getenv("BRAND_PDF_LOGO", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.extend((Path("static/favicon-192.png"), Path("frontend/public/favicon-192.png")))
    return next((path for path in candidates if path.is_file()), None)


def _draw_logo(c: canvas.Canvas, path: Path, x: float, y: float, box: float) -> None:
    """Draw the logo contained in a square, preserving its original proportions."""
    image = ImageReader(str(path))
    image_width, image_height = image.getSize()
    scale = min(box / image_width, box / image_height)
    width, height = image_width * scale, image_height * scale
    c.drawImage(
        image,
        x + (box - width) / 2,
        y + (box - height) / 2,
        width=width,
        height=height,
        preserveAspectRatio=True,
        anchor="c",
        mask="auto",
    )


def build_tickets_pdf(rows: Iterable[dict]) -> bytes:
    """Render the canonical Yendiin ticket PDF used by email and downloads."""
    tickets = list(rows or [])
    output = io.BytesIO()
    c = canvas.Canvas(output, pagesize=A4, pageCompression=1)
    page_width, page_height = A4
    logo = _logo_path()

    for index, row in enumerate(tickets, start=1):
        # Page and ticket frame.
        c.setFillColorRGB(*LIGHT)
        c.rect(0, 0, page_width, page_height, stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setStrokeColorRGB(226 / 255, 232 / 255, 240 / 255)
        c.setLineWidth(1)
        c.roundRect(30, 42, page_width - 60, page_height - 84, 18, stroke=1, fill=1)

        # Strong branded header with a square logo holder.
        c.setFillColorRGB(*NAVY)
        c.roundRect(30, page_height - 158, page_width - 60, 116, 18, stroke=0, fill=1)
        c.setFillColorRGB(*PURPLE)
        c.roundRect(30, page_height - 158, 7, 116, 3, stroke=0, fill=1)
        if logo:
            _draw_logo(c, logo, 54, page_height - 133, 58)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica-Bold", 23)
        c.drawString(130, page_height - 91, "Yendiin")
        c.setFillColorRGB(203 / 255, 213 / 255, 225 / 255)
        c.setFont("Helvetica", 10)
        c.drawString(130, page_height - 111, "Tu entrada, lista para disfrutar")
        c.setFillColorRGB(*PINK)
        c.roundRect(page_width - 164, page_height - 105, 104, 27, 13, stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(page_width - 112, page_height - 95, "CONFIRMADA")

        event_title = _fit(row.get("event_title") or row.get("event_slug") or "Evento", "Helvetica-Bold", 20, page_width - 110)
        c.setFillColorRGB(*NAVY)
        c.setFont("Helvetica-Bold", 20)
        c.drawString(54, page_height - 198, event_title)
        c.setFillColorRGB(*SLATE)
        c.setFont("Helvetica", 9)
        c.drawString(54, page_height - 218, f"ENTRADA {index} DE {len(tickets)}")

        # Information panel.
        panel_x, panel_y, panel_w, panel_h = 54, page_height - 430, 285, 180
        c.setFillColorRGB(*LIGHT)
        c.roundRect(panel_x, panel_y, panel_w, panel_h, 12, stroke=0, fill=1)
        fields = [
            ("Titular", row.get("buyer_name")),
            ("Email", row.get("buyer_email")),
            ("Tipo", row.get("ticket_type") or "General"),
            ("Fecha", _date(row.get("event_date"))),
            ("Hora", row.get("event_time")),
            ("Lugar", row.get("venue")),
            ("Dirección", row.get("event_address")),
            ("Ciudad", row.get("city")),
        ]
        y = panel_y + panel_h - 24
        for label, value in fields:
            c.setFillColorRGB(*SLATE)
            c.setFont("Helvetica-Bold", 8)
            c.drawString(panel_x + 16, y, label.upper())
            c.setFillColorRGB(*NAVY)
            c.setFont("Helvetica", 9)
            c.drawString(panel_x + 82, y, _fit(value, "Helvetica", 9, panel_w - 105))
            y -= 19

        # QR has its own card and generous quiet zone for reliable scanning.
        qr_payload = _text(row.get("qr_payload") or row.get("ticket_id"), "YENDIIN")
        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
        qr.add_data(qr_payload)
        qr.make(fit=True)
        qr_image = qr.make_image(fill_color="black", back_color="white")
        qr_buffer = io.BytesIO()
        qr_image.save(qr_buffer, format="PNG")
        qr_buffer.seek(0)
        qr_x, qr_y, qr_size = page_width - 224, panel_y + 13, 146
        c.setFillColorRGB(1, 1, 1)
        c.setStrokeColorRGB(226 / 255, 232 / 255, 240 / 255)
        c.roundRect(qr_x - 10, qr_y - 10, qr_size + 20, qr_size + 35, 12, stroke=1, fill=1)
        c.drawImage(ImageReader(qr_buffer), qr_x, qr_y + 15, qr_size, qr_size, preserveAspectRatio=True, mask="auto")
        c.setFillColorRGB(*SLATE)
        c.setFont("Helvetica-Bold", 7)
        c.drawCentredString(qr_x + qr_size / 2, qr_y, "PRESENTÁ ESTE QR EN EL INGRESO")

        ticket_id = _text(row.get("ticket_id"))
        c.setFillColorRGB(*SLATE)
        c.setFont("Helvetica", 8)
        c.drawString(54, 77, "Código de entrada")
        c.setFillColorRGB(*NAVY)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(54, 63, _fit(ticket_id, "Helvetica-Bold", 8, page_width - 180))
        c.setFillColorRGB(*SLATE)
        c.setFont("Helvetica", 8)
        c.drawRightString(page_width - 54, 63, "yendiin.com")
        c.showPage()

    c.save()
    return output.getvalue()
