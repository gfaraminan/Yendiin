from fastapi.testclient import TestClient

from app.main import app
from app.routers.orders import _table_columns


class _DescriptionOnlyCursor:
    def __init__(self):
        self.description = []
        self._rows = []

    def execute(self, query, params=None):
        q = " ".join(str(query).split()).lower()
        if "from information_schema.columns" in q:
            self.description = [("column_name",)]
            self._rows = []
            return self
        if q.startswith("select * from orders where 1=0"):
            self.description = [("id",), ("tenant_id",), ("event_slug",)]
            self._rows = []
            return self
        return self

    def fetchall(self):
        return self._rows


def test_table_columns_falls_back_to_cursor_description_when_information_schema_empty():
    cur = _DescriptionOnlyCursor()

    assert _table_columns(cur, "orders") == {"id", "tenant_id", "event_slug"}


class _CheckoutCursor:
    def __init__(self):
        self.description = []
        self._next_fetchone = None
        self._next_fetchall = []
        self.inserted_orders = []

    def execute(self, query, params=None):
        q = " ".join(str(query).split()).lower()
        if "from information_schema.columns" in q:
            table = params[0] if params else None
            self.description = [("column_name",)]
            if table == "events":
                self._next_fetchall = [
                    {"column_name": "slug"},
                    {"column_name": "title"},
                    {"column_name": "tenant_id"},
                    {"column_name": "tenant"},
                    {"column_name": "active"},
                ]
            elif table == "sale_items":
                self._next_fetchall = [
                    {"column_name": "id"},
                    {"column_name": "name"},
                    {"column_name": "price_cents"},
                    {"column_name": "active"},
                    {"column_name": "tenant"},
                    {"column_name": "event_slug"},
                    {"column_name": "kind"},
                    {"column_name": "stock_total"},
                    {"column_name": "stock_sold"},
                ]
            elif table == "orders":
                # Simulates the Render failure: information_schema does not expose
                # orders, but unqualified SELECT * can resolve it.
                self._next_fetchall = []
            else:
                self._next_fetchall = []
            return self
        if q.startswith("select * from orders where 1=0"):
            self.description = [
                ("id",),
                ("tenant_id",),
                ("event_slug",),
                ("producer_tenant",),
                ("items_json",),
                ("total_cents",),
                ("status",),
                ("payment_method",),
                ("seller_code",),
                ("buyer_email",),
                ("buyer_name",),
                ("buyer_phone",),
                ("buyer_dni",),
                ("created_at",),
            ]
            return self
        if "from events" in q and "where tenant_id=%s and slug=%s" in q:
            self.description = [("slug",), ("title",), ("tenant",)]
            self._next_fetchone = {"slug": "rock-fest", "title": "Rock Fest", "tenant": "owner-tenant"}
            return self
        if "from sale_items" in q and "where tenant=%s" in q:
            self.description = [
                ("id",),
                ("name",),
                ("price_cents",),
                ("active",),
                ("stock_total",),
                ("stock_sold",),
            ]
            self._next_fetchone = {
                "id": 10,
                "name": "General",
                "price_cents": 150000,
                "active": True,
                "stock_total": 100,
                "stock_sold": 0,
            }
            return self
        if q.startswith("insert into orders"):
            self.inserted_orders.append((query, params))
            return self
        # Best-effort schema DDL from _ensure_orders_schema.
        return self

    def fetchone(self):
        value = self._next_fetchone
        self._next_fetchone = None
        return value

    def fetchall(self):
        value = self._next_fetchall
        self._next_fetchall = []
        return value


class _CheckoutConn:
    def __init__(self):
        self.cur = _CheckoutCursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cur

    def commit(self):
        return None


def test_create_order_uses_description_fallback_for_orders_schema(monkeypatch):
    conn = _CheckoutConn()

    def _fake_conn_cm(*args, **kwargs):
        return conn

    monkeypatch.setattr("app.routers.orders._conn_cm", _fake_conn_cm)
    client = TestClient(app)

    resp = client.post(
        "/api/orders/create",
        json={
            "tenant_id": "default",
            "event_slug": "rock-fest",
            "sale_item_id": 10,
            "quantity": 1,
            "payment_method": "mp",
            "buyer": {
                "full_name": "Comprador Test",
                "email": "buyer@example.com",
                "phone": "2615551234",
                "dni": "12345678",
            },
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["checkout_url"] is None
    assert len(conn.cur.inserted_orders) == 1
