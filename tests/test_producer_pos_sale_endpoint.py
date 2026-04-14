from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class _FakeCursorResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakePosConn:
    def __init__(self, *, stock_total=100, stock_sold=10):
        self.stock_total = stock_total
        self.stock_sold = stock_sold
        self.queries = []
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self):
        self.committed = True

    def execute(self, query, params=None):
        q = " ".join(str(query).split()).lower()
        self.queries.append((q, params))

        if "information_schema.columns" in q and "table_name" in q:
            table = (params or [None, None])[1]
            if table == "sale_items":
                return _FakeCursorResult(
                    [
                        {"column_name": "id"},
                        {"column_name": "tenant"},
                        {"column_name": "event_slug"},
                        {"column_name": "name"},
                        {"column_name": "kind"},
                        {"column_name": "price_cents"},
                        {"column_name": "stock_total"},
                        {"column_name": "stock_sold"},
                        {"column_name": "updated_at"},
                    ]
                )
            if table == "orders":
                return _FakeCursorResult(
                    [
                        {"column_name": "id"},
                        {"column_name": "tenant_id"},
                        {"column_name": "event_slug"},
                        {"column_name": "producer_tenant"},
                        {"column_name": "source"},
                        {"column_name": "items_json"},
                        {"column_name": "total_cents"},
                        {"column_name": "base_amount"},
                        {"column_name": "fee_amount"},
                        {"column_name": "total_amount"},
                        {"column_name": "status"},
                        {"column_name": "payment_method"},
                        {"column_name": "seller_code"},
                        {"column_name": "buyer_name"},
                        {"column_name": "buyer_email"},
                        {"column_name": "buyer_phone"},
                        {"column_name": "buyer_dni"},
                        {"column_name": "customer_label"},
                        {"column_name": "auth_provider"},
                        {"column_name": "auth_subject"},
                        {"column_name": "created_at"},
                    ]
                )
            if table == "tickets":
                return _FakeCursorResult(
                    [
                        {"column_name": "id"},
                        {"column_name": "order_id"},
                        {"column_name": "tenant_id"},
                        {"column_name": "producer_tenant"},
                        {"column_name": "event_slug"},
                        {"column_name": "sale_item_id"},
                        {"column_name": "qr_token"},
                        {"column_name": "status"},
                        {"column_name": "created_at"},
                        {"column_name": "updated_at"},
                        {"column_name": "ticket_type"},
                        {"column_name": "qr_payload"},
                        {"column_name": "buyer_phone"},
                        {"column_name": "buyer_dni"},
                    ]
                )
            return _FakeCursorResult([])

        if "from sale_items si" in q:
            return _FakeCursorResult(
                [
                    {
                        "id": 10,
                        "name": "General",
                        "price_cents": 2500,
                        "kind": "ticket",
                        "stock_total": self.stock_total,
                        "stock_sold": self.stock_sold,
                    }
                ]
            )

        return _FakeCursorResult([])


def test_pos_sale_creates_paid_order_emits_tickets_and_updates_stock():
    fake_conn = _FakePosConn(stock_total=100, stock_sold=4)
    payload = {
        "tenant_id": "default",
        "sale_item_id": 10,
        "quantity": 2,
        "payment_method": "cash",
        "buyer_name": "Juan Perez",
        "buyer_phone": "11223344",
        "buyer_dni": "30111222",
        "seller_code": "STAFF01",
    }

    with patch("app.routers.producer.get_conn", return_value=fake_conn), patch(
        "app.routers.producer._can_edit_event", return_value=True
    ):
        client = TestClient(app)
        resp = client.post(
            "/api/producer/events/fiesta-2026/pos-sale?tenant_id=default",
            headers={"x-producer": "prodtest"},
            json=payload,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["mode"] == "pos"
    assert data["payment_method"] == "cash"
    assert data["quantity"] == 2
    assert data["total_cents"] == 5000
    assert len(data["tickets"]) == 2
    assert fake_conn.committed is True

    executed_sql = "\n".join(q for q, _ in fake_conn.queries)
    assert "insert into orders" in executed_sql
    assert "insert into tickets" in executed_sql
    assert "update sale_items" in executed_sql


def test_pos_sale_rejects_invalid_payment_method_before_db_access():
    fake_conn = _FakePosConn()
    payload = {
        "tenant_id": "default",
        "sale_item_id": 10,
        "quantity": 1,
        "payment_method": "crypto",
    }

    with patch("app.routers.producer.get_conn", return_value=fake_conn), patch(
        "app.routers.producer._can_edit_event", return_value=True
    ):
        client = TestClient(app)
        resp = client.post(
            "/api/producer/events/fiesta-2026/pos-sale?tenant_id=default",
            headers={"x-producer": "prodtest"},
            json=payload,
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_payment_method"
    assert fake_conn.queries == []


def test_pos_sale_returns_stock_insufficient():
    fake_conn = _FakePosConn(stock_total=5, stock_sold=5)
    payload = {
        "tenant_id": "default",
        "sale_item_id": 10,
        "quantity": 1,
        "payment_method": "cash",
    }

    with patch("app.routers.producer.get_conn", return_value=fake_conn), patch(
        "app.routers.producer._can_edit_event", return_value=True
    ):
        client = TestClient(app)
        resp = client.post(
            "/api/producer/events/fiesta-2026/pos-sale?tenant_id=default",
            headers={"x-producer": "prodtest"},
            json=payload,
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "stock_insufficient"


def test_pos_sale_staff_token_takes_precedence_over_logged_user():
    fake_conn = _FakePosConn(stock_total=100, stock_sold=0)
    payload = {
        "tenant_id": "default",
        "sale_item_id": 10,
        "quantity": 1,
        "payment_method": "cash",
    }

    with patch("app.routers.producer.get_conn", return_value=fake_conn), patch(
        "app.routers.producer.require_staff_token_for_event",
        return_value={"seller_name": "Caja Staff"},
    ), patch(
        "app.routers.producer._resolve_event_owner_slug",
        return_value="owner-prod",
    ), patch(
        "app.routers.producer._require_auth",
        return_value={"producer": "otro-prod", "email": "otro@demo.com"},
    ), patch(
        "app.routers.producer._can_edit_event",
        side_effect=lambda tenant_id, event_slug, producer: producer == "owner-prod",
    ):
        client = TestClient(app)
        resp = client.post(
            "/api/producer/events/fiesta-2026/pos-sale?tenant_id=default",
            headers={
                "x-producer": "otro-prod",
                "x-staff-token": "staff-token-demo",
            },
            json=payload,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["mode"] == "pos"


class _FakePosSummaryConn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        q = " ".join(str(query).split()).lower()

        if "information_schema.columns" in q and "table_name" in q:
            table = (params or [None, None])[1]
            if table == "orders":
                return _FakeCursorResult(
                    [
                        {"column_name": "id"},
                        {"column_name": "tenant_id"},
                        {"column_name": "event_slug"},
                        {"column_name": "status"},
                        {"column_name": "payment_method"},
                        {"column_name": "auth_provider"},
                        {"column_name": "auth_subject"},
                        {"column_name": "items_json"},
                        {"column_name": "total_cents"},
                        {"column_name": "created_at"},
                    ]
                )
            return _FakeCursorResult([])

        if "from orders o" in q and "as order_id" in q:
            return _FakeCursorResult(
                [
                    {
                        "order_id": "ord-pos-1",
                        "payment_method": "cash",
                        "operator": "caja-1",
                        "total_cents": 5000,
                        "created_at": None,
                    },
                    {
                        "order_id": "ord-pos-2",
                        "payment_method": "card",
                        "operator": "caja-2",
                        "total_cents": 7500,
                        "created_at": None,
                    },
                    {
                        "order_id": "ord-pos-3",
                        "payment_method": "cash",
                        "operator": "caja-1",
                        "total_cents": 2500,
                        "created_at": None,
                    },
                ]
            )

        return _FakeCursorResult([])


def test_pos_sales_summary_groups_by_payment_and_operator():
    fake_conn = _FakePosSummaryConn()
    with patch("app.routers.producer.get_conn", return_value=fake_conn), patch(
        "app.routers.producer._can_edit_event", return_value=True
    ):
        client = TestClient(app)
        resp = client.get(
            "/api/producer/events/fiesta-2026/pos-sales?tenant_id=default",
            headers={"x-producer": "prodtest"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["orders_count"] == 3
    assert data["total_cents"] == 15000

    cash = next((r for r in data["by_payment"] if r["payment_method"] == "cash"), None)
    assert cash is not None
    assert cash["orders"] == 2
    assert cash["total_cents"] == 7500

    op = next((r for r in data["by_operator"] if r["operator"] == "caja-1"), None)
    assert op is not None
    assert op["orders"] == 2
    assert op["total_cents"] == 7500
