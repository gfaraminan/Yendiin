from pathlib import Path

from app.ticket_pdf import _logo_path, build_tickets_pdf


def _ticket(**overrides):
    ticket = {
        "ticket_id": "ticket-123",
        "qr_payload": "YENDIIN:ticket-123",
        "event_title": "Una noche inolvidable",
        "buyer_name": "Cliente Yendiin",
        "buyer_email": "cliente@example.com",
        "ticket_type": "General",
        "event_date": "29/07/2026",
        "event_time": "21:00",
        "venue": "Estadio Central",
        "event_address": "Avenida Siempre Viva 123",
        "city": "Mendoza",
    }
    ticket.update(overrides)
    return ticket


def test_build_tickets_pdf_creates_one_branded_page_per_ticket():
    pdf = build_tickets_pdf([_ticket(), _ticket(ticket_id="ticket-456")])

    assert pdf.startswith(b"%PDF-")
    assert pdf.count(b"/Type /Page\n") == 2
    assert len(pdf) > 5_000


def test_renderer_uses_the_official_yendiin_logo_asset():
    assert _logo_path() == Path("frontend/public/Logo Blanco Png fondo transparente.png")


def test_email_renderer_uses_the_canonical_download_renderer(monkeypatch):
    from app.routers.payments_mp import _build_tickets_pdf_bytes
    import app.ticket_pdf

    rows = [_ticket()]
    expected = b"canonical-yendiin-pdf"
    monkeypatch.setattr(app.ticket_pdf, "build_tickets_pdf", lambda received: expected if received is rows else b"")

    assert _build_tickets_pdf_bytes(rows) == expected


def test_renderer_accepts_long_values_without_overflow(tmp_path: Path):
    pdf = build_tickets_pdf(
        [_ticket(event_title="Festival " * 80, event_address="Dirección muy extensa " * 80)]
    )

    output = tmp_path / "ticket.pdf"
    output.write_bytes(pdf)
    assert output.stat().st_size > 5_000
