from unittest.mock import patch

from app.routers.orders import _send_transfer_notification_email


def test_send_transfer_notification_email_calls_mailer_with_expected_payload():
    with patch("app.routers.orders.send_email") as send_email_mock:
        _send_transfer_notification_email(
            to_email="nuevo@cliente.com",
            from_email="anterior@cliente.com",
            order_id="ORD-123",
            event_slug="recital-rock",
            ticket_id="TICKET-1",
        )

    send_email_mock.assert_called_once()
    kwargs = send_email_mock.call_args.kwargs
    assert kwargs["to_email"] == "nuevo@cliente.com"
    assert "ORD-123" in kwargs["subject"]
    assert "anterior@cliente.com" in kwargs["text"]
    assert "recital-rock" in kwargs["text"]
    assert "TICKET-1" in kwargs["html"]
