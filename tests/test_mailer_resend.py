import base64
import json
from unittest.mock import patch

from app.mailer import send_email


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def getcode(self):
        return 200

    def read(self):
        return b'{"id":"email_123"}'


def test_send_email_prefers_resend_api_when_key_is_configured(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("RESEND_API_URL", "https://api.resend.test/emails")
    monkeypatch.setenv("MAIL_FROM", "Yendiin <tickets@mail.yendiin.com>")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASS", raising=False)

    with patch("app.mailer.urllib.request.urlopen", return_value=_FakeResponse()) as urlopen_mock:
        send_email(
            to_email="cliente@example.com",
            subject="Tus tickets",
            text="Adjuntamos tus tickets.",
            html="<p>Adjuntamos tus tickets.</p>",
            attachments=[("ticket.pdf", b"pdf-bytes", "application/pdf")],
        )

    request = urlopen_mock.call_args.args[0]
    assert request.full_url == "https://api.resend.test/emails"
    assert request.headers["Authorization"] == "Bearer re_test_key"

    payload = json.loads(request.data.decode("utf-8"))
    assert payload["from"] == "Yendiin <tickets@mail.yendiin.com>"
    assert payload["to"] == ["cliente@example.com"]
    assert payload["subject"] == "Tus tickets"
    assert payload["text"] == "Adjuntamos tus tickets."
    assert payload["html"] == "<p>Adjuntamos tus tickets.</p>"
    assert payload["attachments"] == [
        {
            "filename": "ticket.pdf",
            "content": base64.b64encode(b"pdf-bytes").decode("ascii"),
        }
    ]


def test_send_email_uses_smtp_fallback_without_resend_key(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_USER", "smtp-user")
    monkeypatch.setenv("SMTP_PASS", "smtp-pass")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("MAIL_FROM", "Yendiin <tickets@example.test>")

    with patch("app.mailer._send_via_smtp") as smtp_mock:
        send_email(to_email="cliente@example.com", subject="Hola", text="Texto")

    smtp_mock.assert_called_once_with(
        to_email="cliente@example.com",
        subject="Hola",
        text="Texto",
        html=None,
        attachments=None,
    )
