import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.support_ai.service import SupportAIService


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeOpenAIClient:
    def __init__(self):
        self.calls = 0

    def post(self, url, headers=None, json=None, timeout=45):
        self.calls += 1
        if self.calls == 1:
            return _FakeResponse(
                {
                    "id": "resp_1",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call_1",
                            "name": "get_order",
                            "arguments": '{"tenant_id":"default","order_id":"ORD-1"}',
                        }
                    ],
                }
            )
        return _FakeResponse(
            {
                "id": "resp_2",
                "output_text": "Tu orden está paga.",
            }
        )


class _FakeTools:
    def with_request_context(self, context, user_message):
        return self

    @property
    def specs(self):
        return [
            {
                "type": "function",
                "name": "get_order",
                "parameters": {"type": "object", "properties": {}},
            }
        ]

    def run(self, name, arguments_json):
        return type("ToolResult", (), {"payload": {"order": {"status": "paid"}}})


class _FakeCursor:
    def __init__(self):
        self.rowcount = 0
        self._next_fetchone = None
        self._next_fetchall = []

    def execute(self, query, params=None):
        q = " ".join(str(query).split()).lower()
        if "count(*) filter (where active=true)" in q:
            self._next_fetchone = {"active_events": 2, "total_events": 5}
            return
        if "from orders" in q and "paid_orders" in q:
            self._next_fetchone = {"paid_orders": 7, "revenue_cents": 123450}
            return
        if "from tickets t" in q and "count(*)::bigint as total_tickets_sold" in q:
            self._next_fetchone = {"total_tickets_sold": 33}
            return
        if "as total_bar_orders" in q and "bar_revenue_cents" in q:
            self._next_fetchone = {"total_bar_orders": 4, "bar_revenue_cents": 45600}
            return
        if "count(distinct lower(o.buyer_email))" in q:
            self._next_fetchone = {"unique_buyers": 9}
            return
        if "left join tickets t" in q and "group by e.slug" in q:
            self._next_fetchall = [{"slug": "rock-fest", "title": "Rock Fest", "tickets_sold": 33}]
            return
        if "group by o.event_slug" in q and "bar_revenue" in q:
            self._next_fetchall = [{"event_slug": "rock-fest", "total_revenue": 123450, "bar_revenue": 45600}]
            return
        if "from orders" in q and "coalesce(source,'')='bar'" in q and "limit %s" in q:
            self._next_fetchall = [
                {"id": "ORD-BAR-1", "created_at": "2026-01-01T10:00:00", "status": "PAID", "buyer_email": "buyer@mail.com", "total_cents": 12000},
            ]
            return
        if "select slug, title, tenant, producer" in q:
            self._next_fetchall = [{"slug": "rock-fest", "title": "Rock Fest"}]
            return
        if "information_schema.columns" in q and "table_name='events'" in q:
            self._next_fetchall = [
                {"column_name": "slug"},
                {"column_name": "title"},
                {"column_name": "tenant_id"},
                {"column_name": "tenant"},
                {"column_name": "producer"},
                {"column_name": "active"},
                {"column_name": "visibility"},
                {"column_name": "city"},
                {"column_name": "date_text"},
                {"column_name": "venue"},
                {"column_name": "description"},
                {"column_name": "flyer_url"},
                {"column_name": "hero_bg"},
            ]
            return
        if "information_schema.columns" in q and "table_name='orders'" in q:
            self._next_fetchall = [
                {"column_name": "buyer_email"},
                {"column_name": "source"},
                {"column_name": "bar_slug"},
                {"column_name": "order_kind"},
                {"column_name": "kind"},
            ]
            return
        if "information_schema.columns" in q and "table_name='sale_items'" in q:
            self._next_fetchall = [
                {"column_name": "id"},
                {"column_name": "tenant"},
                {"column_name": "event_slug"},
                {"column_name": "name"},
                {"column_name": "kind"},
                {"column_name": "price_cents"},
                {"column_name": "stock_total"},
                {"column_name": "stock_sold"},
                {"column_name": "active"},
                {"column_name": "display_order"},
            ]
            return
        if "select 1 from events" in q:
            self._next_fetchone = None
            return
        if "insert into events" in q:
            self._next_fetchone = {"slug": "evento-ceo"}
            return
        if "update events" in q and "set active" in q:
            self.rowcount = 1
            return
        if "update events set" in q and "returning slug" in q:
            self._next_fetchone = {"slug": "rock-fest"}
            self.rowcount = 1
            return
        if "select slug, tenant from events" in q:
            self._next_fetchone = {"slug": "rock-fest", "tenant": "owner-mail-com"}
            return
        if "count(*)::bigint as paid_count" in q:
            self._next_fetchone = {"paid_count": 0}
            return
        if "delete from sale_items" in q:
            self.rowcount = 1
            return
        if "delete from events" in q:
            self.rowcount = 1
            return
        if "select tenant, producer, producer_id from events" in q:
            self._next_fetchone = {"tenant": "owner-mail-com", "producer": None, "producer_id": None}
            return
        if "select tenant from events" in q:
            self._next_fetchone = {"tenant": "owner-mail-com"}
            return
        if "from sale_items" in q and "order by display_order" in q:
            self._next_fetchall = [{"id": 1, "name": "General", "kind": "ticket", "price_cents": 1000, "active": True}]
            return
        if "insert into sale_items" in q:
            self._next_fetchone = {"id": 99}
            return
        if "support_ai_event_delete_requests" in q and "where id=%s" in q:
            self._next_fetchone = {"id": 1, "tenant_id": "default", "event_slug": "rock-fest", "status": "pending"}
            return
        if "support_ai_event_delete_requests" in q and "select id, tenant_id" in q:
            self._next_fetchall = [{"id": 1, "tenant_id": "default", "event_slug": "rock-fest", "producer_email": "prod@mail.com", "reason": "cancelado", "status": "pending"}]
            return
        if "support_ai_event_delete_requests" in q and "update support_ai_event_delete_requests" in q:
            self.rowcount = 1
            return
        if "update sale_items" in q and "set active" in q:
            self.rowcount = 1
            return
        if "update events" in q:
            self.rowcount = 1
            return

    def fetchone(self):
        value = self._next_fetchone
        self._next_fetchone = None
        return value

    def fetchall(self):
        value = self._next_fetchall
        self._next_fetchall = []
        return value


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return _FakeCursor()


class _ProducerOnlyCursor(_FakeCursor):
    def execute(self, query, params=None):
        q = " ".join(str(query).split()).lower()
        if "information_schema.columns" in q and "table_name='sale_items'" in q:
            self._next_fetchall = [
                {"column_name": "tenant"},
                {"column_name": "event_slug"},
                {"column_name": "name"},
                {"column_name": "kind"},
                {"column_name": "price_cents"},
                {"column_name": "currency"},
                {"column_name": "stock_total"},
                {"column_name": "display_order"},
                {"column_name": "active"},
            ]
            return
        if "select tenant, producer, producer_id from events" in q:
            self._next_fetchone = {"tenant": "", "producer": "prod-owner", "producer_id": None}
            return
        if "insert into sale_items" in q:
            self._next_fetchone = {"id": 321}
            return
        super().execute(query, params)


class _ProducerOnlyConn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return _ProducerOnlyCursor()


class SupportAIEndpointTests(unittest.TestCase):
    def test_status_endpoint_reports_readiness(self):
        os.environ["SUPPORT_AI_ENABLED"] = "true"
        os.environ["SUPPORT_AI_MODEL"] = "gpt-5-mini"
        os.environ["OPENAI_API_KEY"] = "test-key"
        os.environ["OPENAI_VECTOR_STORE_ID"] = "vs_123"

        with patch("app.routers.support_ai._is_staff_user", return_value=True):
            client = TestClient(app)
            resp = client.get("/api/support/ai/status")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["enabled"])
        self.assertTrue(data["is_staff"])
        self.assertTrue(data["has_openai_key"])
        self.assertTrue(data["has_vector_store"])

    def test_chat_endpoint_requires_staff_user(self):
        os.environ["SUPPORT_AI_ENABLED"] = "true"
        client = TestClient(app)
        resp = client.post("/api/support/ai/chat", json={"message": "hola"})
        self.assertEqual(resp.status_code, 403)

    def test_chat_endpoint_disabled_by_feature_flag(self):
        os.environ["SUPPORT_AI_ENABLED"] = "false"
        client = TestClient(app)
        resp = client.post("/api/support/ai/chat", json={"message": "hola"})
        self.assertEqual(resp.status_code, 503)

    def test_chat_endpoint_with_mocked_openai_client(self):
        os.environ["SUPPORT_AI_ENABLED"] = "true"
        os.environ["OPENAI_API_KEY"] = "test-key"

        fake_client = _FakeOpenAIClient()
        fake_service = SupportAIService(http_client=fake_client, tools=_FakeTools())

        with patch("app.routers.support_ai._is_staff_user", return_value=True), patch("app.routers.support_ai.get_support_ai_service", return_value=fake_service):
            client = TestClient(app)
            resp = client.post(
                "/api/support/ai/chat",
                json={"message": "¿cómo está mi orden?", "tenant_id": "default"},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["answer"], "Tu orden está paga.")
        self.assertIn("get_order", data["used_tools"])
        self.assertEqual(data["trace_id"], "resp_2")

    def test_admin_dashboard_endpoint(self):
        os.environ["SUPPORT_AI_ENABLED"] = "true"
        with patch("app.routers.support_ai._is_staff_user", return_value=True), patch("app.routers.support_ai.get_conn", return_value=_FakeConn()):
            client = TestClient(app)
            resp = client.get("/api/support/ai/admin/dashboard?tenant_id=default")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["active_events"], 2)
        self.assertEqual(data["total_events"], 5)
        self.assertEqual(data["paid_orders"], 7)
        self.assertEqual(data["revenue_cents"], 123450)
        self.assertEqual(data["total_tickets_sold"], 33)
        self.assertEqual(data["total_bar_orders"], 4)
        self.assertEqual(data["bar_revenue_cents"], 45600)
        self.assertEqual(data["unique_buyers"], 9)
        self.assertEqual(len(data["events"]), 1)

    def test_admin_create_and_transfer_endpoints(self):
        os.environ["SUPPORT_AI_ENABLED"] = "true"
        with patch("app.routers.support_ai._is_staff_user", return_value=True), patch("app.routers.support_ai.get_conn", return_value=_FakeConn()):
            client = TestClient(app)
            create_resp = client.post(
                "/api/support/ai/admin/events/create",
                json={"tenant_id": "default", "title": "Evento CEO", "owner_tenant": "cliente@example.com"},
            )
            transfer_resp = client.post(
                "/api/support/ai/admin/events/transfer",
                json={"tenant_id": "default", "event_slug": "evento-ceo", "new_owner_tenant": "nuevo-owner"},
            )

        self.assertEqual(create_resp.status_code, 200)
        self.assertEqual(create_resp.json()["owner"], "cliente-example-com")
        self.assertEqual(transfer_resp.status_code, 200)
        self.assertEqual(transfer_resp.json()["new_owner"], "nuevo-owner")

    def test_admin_update_event_endpoint(self):
        os.environ["SUPPORT_AI_ENABLED"] = "true"
        with patch("app.routers.support_ai._is_staff_user", return_value=True), patch("app.routers.support_ai.get_conn", return_value=_FakeConn()):
            client = TestClient(app)
            resp = client.post(
                "/api/support/ai/admin/events/update",
                json={
                    "tenant_id": "default",
                    "event_slug": "rock-fest",
                    "title": "Rock Fest Updated",
                    "visibility": "public",
                    "settlement_mode": "manual_transfer",
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["event_slug"], "rock-fest")

    def test_admin_pause_delete_and_sale_items_endpoints(self):
        os.environ["SUPPORT_AI_ENABLED"] = "true"
        with patch("app.routers.support_ai._is_staff_user", return_value=True), patch("app.routers.support_ai.get_conn", return_value=_FakeConn()):
            client = TestClient(app)
            pause_resp = client.post("/api/support/ai/admin/events/pause", json={"tenant_id": "default", "event_slug": "rock-fest", "is_active": False})
            list_resp = client.get("/api/support/ai/admin/sale-items?tenant_id=default&event_slug=rock-fest")
            create_item_resp = client.post("/api/support/ai/admin/sale-items/create", json={"tenant_id": "default", "event_slug": "rock-fest", "name": "General", "price_cents": 1000})
            toggle_item_resp = client.post("/api/support/ai/admin/sale-items/toggle", json={"tenant_id": "default", "event_slug": "rock-fest", "id": 99, "active": False})
            delete_item_resp = client.delete("/api/support/ai/admin/sale-items/99?tenant_id=default&event_slug=rock-fest")
            delete_resp = client.post("/api/support/ai/admin/events/delete", json={"tenant_id": "default", "event_slug": "rock-fest", "confirm_text": "ELIMINAR"})

        self.assertEqual(pause_resp.status_code, 200)
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(create_item_resp.status_code, 200)
        self.assertEqual(toggle_item_resp.status_code, 200)
        self.assertEqual(delete_item_resp.status_code, 200)
        self.assertEqual(delete_resp.status_code, 200)


    def test_admin_bar_sales_detail_endpoint(self):
        os.environ["SUPPORT_AI_ENABLED"] = "true"
        with patch("app.routers.support_ai._is_staff_user", return_value=True), patch("app.routers.support_ai.get_conn", return_value=_FakeConn()):
            client = TestClient(app)
            resp = client.get("/api/support/ai/admin/bar-sales?tenant_id=default&event_slug=rock-fest")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["orders_count"], 1)
        self.assertEqual(data["bar_revenue_cents"], 12000)

    def test_admin_sale_item_create_uses_event_producer_when_tenant_missing(self):
        os.environ["SUPPORT_AI_ENABLED"] = "true"
        with patch("app.routers.support_ai._is_staff_user", return_value=True), patch("app.routers.support_ai.get_conn", return_value=_ProducerOnlyConn()):
            client = TestClient(app)
            resp = client.post(
                "/api/support/ai/admin/sale-items/create",
                json={"tenant_id": "default", "event_slug": "rock-fest", "name": "VIP", "price_cents": 25000},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["producer"], "prod-owner")

    def test_admin_delete_requests_endpoints(self):
        os.environ["SUPPORT_AI_ENABLED"] = "true"
        with patch("app.routers.support_ai._is_staff_user", return_value=True), patch("app.routers.support_ai.get_conn", return_value=_FakeConn()):
            client = TestClient(app)
            list_resp = client.get("/api/support/ai/admin/events/delete-requests?tenant_id=default&status=pending")
            resolve_resp = client.post(
                "/api/support/ai/admin/events/delete-requests/resolve",
                json={"request_id": 1, "approve": False, "resolution_note": "rechazado"},
            )

        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(resolve_resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
