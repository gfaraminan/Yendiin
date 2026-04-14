import unittest
from unittest.mock import patch

from app.support_ai.tools import SupportAITools


class _PaidOrderTools(SupportAITools):
    def get_order(self, tenant_id: str, order_id: str):
        return {"order": {"id": order_id, "status": "paid"}}


class SupportAIToolsTests(unittest.TestCase):
    def test_specs_include_executive_metrics_tools(self):
        tools = SupportAITools()
        names = {t.get("name") for t in tools.specs}
        self.assertIn("get_event_ticket_sales_today", names)
        self.assertIn("get_total_ticket_sales_today", names)
        self.assertIn("get_service_charge_last_days", names)
        self.assertIn("find_events_by_query", names)
        self.assertIn("get_event_ticket_sales_today_by_name", names)

    def test_resend_requires_explicit_confirmation_flag(self):
        tools = _PaidOrderTools(request_context={}, user_message="reenviar ORD-1 a x@y.com")
        res = tools.resend_order_email("default", "ORD-1", "x@y.com")
        self.assertFalse(res["ok"])
        self.assertIn("confirmación", res["error"])

    def test_resend_with_context_confirmation_allows_send(self):
        tools = _PaidOrderTools(
            request_context={"confirm_resend_order_email": True},
            user_message="por favor reenviar confirmación",
        )
        with patch("app.support_ai.tools.send_email") as mocked_send:
            res = tools.resend_order_email("default", "ORD-1", "x@y.com")
        self.assertTrue(res["ok"])
        mocked_send.assert_called_once()

    def test_resend_accepts_confirmation_phrase_in_message(self):
        tools = _PaidOrderTools(
            request_context={},
            user_message="confirmo reenviar la orden ORD-1 a x@y.com",
        )
        with patch("app.support_ai.tools.send_email") as mocked_send:
            res = tools.resend_order_email("default", "Order #ORD-1", "x@y.com")
        self.assertTrue(res["ok"])
        mocked_send.assert_called_once()

    def test_resend_sends_email_when_all_guardrails_pass(self):
        tools = _PaidOrderTools(
            request_context={"confirm_resend_order_email": True},
            user_message="reenviar ORD-1 a x@y.com",
        )
        with patch("app.support_ai.tools.send_email") as mocked_send:
            res = tools.resend_order_email("default", "ORD-1", "x@y.com")
        self.assertTrue(res["ok"])
        mocked_send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
