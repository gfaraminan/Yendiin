import asyncio

from app.routers import payments_mp


class _DummyMPResponse:
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


class _DummyAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None, params=None):
        return _DummyMPResponse()


def test_mp_sync_order_sends_confirmation_email_after_finalize(monkeypatch):
    sent = {}

    def fake_finalize(*, order_id, payment_id):
        sent["finalized"] = (order_id, payment_id)
        return True

    def fake_send_email(request, *, order_id, payment_id=None, force=False):
        sent["email"] = (order_id, payment_id, force)
        return {"sent": True, "to_email": "buyer@example.com"}

    monkeypatch.setattr(payments_mp, "MP_ACCESS_TOKEN", "APP_USR-test")
    monkeypatch.setattr(payments_mp.httpx, "AsyncClient", _DummyAsyncClient)
    monkeypatch.setattr(payments_mp, "_finalize_paid_order", fake_finalize)
    monkeypatch.setattr(payments_mp, "_send_paid_order_confirmation_email", fake_send_email)

    result = asyncio.run(payments_mp.mp_sync_order(object(), order_id="ORD-12345678", tenant="default"))

    assert result["ok"] is True
    assert result["status"] == "paid"
    assert result["processed"] is True
    assert result["email"] == {"sent": True, "to_email": "buyer@example.com"}
    assert sent["finalized"] == ("ORD-12345678", "160788460765")
    assert sent["email"] == ("ORD-12345678", "160788460765", False)
