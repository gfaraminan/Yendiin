import asyncio

from app.routers import payments_mp


class _SearchMPResponse:
    status_code = 200
    text = "ok"

    @staticmethod
    def json():
        return {
            "results": [
                {
                    "id": "160788460765",
                    "status": "approved",
                }
            ]
        }


class _DirectMPResponse:
    status_code = 200
    text = "ok"

    @staticmethod
    def json():
        return {
            "id": "160788460765",
            "status": "approved",
            "external_reference": "ORD-12345678",
        }


class _SearchAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None, params=None):
        return _SearchMPResponse()


class _DirectAsyncClient(_SearchAsyncClient):
    async def get(self, url, headers=None, params=None):
        if url.endswith("/v1/payments/160788460765"):
            return _DirectMPResponse()
        raise AssertionError("Direct payment sync should not fall back to search")


def test_mp_sync_order_sends_confirmation_email_after_finalize(monkeypatch):
    sent = {}

    def fake_finalize(*, order_id, payment_id):
        sent["finalized"] = (order_id, payment_id)
        return True

    def fake_send_email(request, *, order_id, payment_id=None, force=False):
        sent["email"] = (order_id, payment_id, force)
        return {"sent": True, "to_email": "buyer@example.com"}

    monkeypatch.setattr(payments_mp, "MP_ACCESS_TOKEN", "APP_USR-test")
    monkeypatch.setattr(payments_mp.httpx, "AsyncClient", _SearchAsyncClient)
    monkeypatch.setattr(payments_mp, "_finalize_paid_order", fake_finalize)
    monkeypatch.setattr(payments_mp, "_send_paid_order_confirmation_email", fake_send_email)

    result = asyncio.run(payments_mp.mp_sync_order(object(), order_id="ORD-12345678", tenant="default"))

    assert result["ok"] is True
    assert result["status"] == "paid"
    assert result["processed"] is True
    assert result["source"] == "search"
    assert result["email"] == {"sent": True, "to_email": "buyer@example.com"}
    assert sent["finalized"] == ("ORD-12345678", "160788460765")
    assert sent["email"] == ("ORD-12345678", "160788460765", False)


def test_mp_sync_order_can_sync_by_payment_id(monkeypatch):
    sent = {}

    def fake_finalize(*, order_id, payment_id):
        sent["finalized"] = (order_id, payment_id)
        return True

    def fake_send_email(request, *, order_id, payment_id=None, force=False):
        sent["email"] = (order_id, payment_id, force)
        return {"sent": True, "to_email": "buyer@example.com"}

    monkeypatch.setattr(payments_mp, "MP_ACCESS_TOKEN", "APP_USR-test")
    monkeypatch.setattr(payments_mp.httpx, "AsyncClient", _DirectAsyncClient)
    monkeypatch.setattr(payments_mp, "_finalize_paid_order", fake_finalize)
    monkeypatch.setattr(payments_mp, "_send_paid_order_confirmation_email", fake_send_email)

    result = asyncio.run(
        payments_mp.mp_sync_order(
            object(),
            order_id="ORD-12345678",
            tenant="default",
            payment_id="160788460765",
        )
    )

    assert result["ok"] is True
    assert result["status"] == "paid"
    assert result["processed"] is True
    assert result["source"] == "payment_id"
    assert sent["finalized"] == ("ORD-12345678", "160788460765")
    assert sent["email"] == ("ORD-12345678", "160788460765", False)


def test_confirmation_attachment_pdf_uses_yendiin_branding(monkeypatch):
    drawn_text = []
    drawn_images = []

    class RecordingCanvas:
        def __init__(self, *_args, **_kwargs):
            pass

        def setStrokeColorRGB(self, *_args):
            pass

        def roundRect(self, *_args, **_kwargs):
            pass

        def drawImage(self, image, *_args, **_kwargs):
            drawn_images.append(image)

        def setFillColorRGB(self, *_args):
            pass

        def setFont(self, *_args):
            pass

        def drawString(self, _x, _y, value):
            drawn_text.append(value)

        def showPage(self):
            pass

        def save(self):
            pass

    monkeypatch.setattr(payments_mp.canvas, "Canvas", RecordingCanvas)

    payments_mp._build_tickets_pdf_bytes(
        [
            {
                "ticket_id": "TICKET-1",
                "qr_payload": "QR-TICKET-1",
                "event_title": "Evento de prueba",
                "buyer_name": "Comprador",
                "buyer_email": "buyer@example.com",
            }
        ]
    )

    assert any("Logo Blanco Png fondo transparente.png" in str(image.fileName) for image in drawn_images)
    assert "Yendiin" not in drawn_text
    assert "TicketPro" not in drawn_text
