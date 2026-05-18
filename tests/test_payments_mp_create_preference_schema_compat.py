from fastapi.testclient import TestClient

from app.main import app
from app.routers import payments_mp


class _PreferenceCursor:
    def __init__(self):
        self.description = []
        self._next_fetchone = None
        self._next_fetchall = []
        self.order_select_sql = ""

    def execute(self, query, params=None):
        q = " ".join(str(query).split()).lower()
        if "from information_schema.columns" in q:
            table = params[0] if params else None
            self.description = [("column_name",)]
            if table == "orders":
                # Legacy checkout schema: no base_amount/fee_amount/total_amount.
                self._next_fetchall = [
                    {"column_name": "id"},
                    {"column_name": "tenant_id"},
                    {"column_name": "event_slug"},
                    {"column_name": "producer_tenant"},
                    {"column_name": "status"},
                    {"column_name": "total_cents"},
                    {"column_name": "items_json"},
                    {"column_name": "buyer_email"},
                    {"column_name": "buyer_name"},
                ]
            elif table == "events":
                self._next_fetchall = [
                    {"column_name": "settlement_mode"},
                    {"column_name": "service_charge_pct"},
                ]
            else:
                self._next_fetchall = []
            return self
        if "from orders" in q and "where tenant_id=%s and id=%s" in q:
            self.order_select_sql = str(query)
            self._next_fetchone = {
                "id": "order-123",
                "tenant_id": "default",
                "event_slug": "rock-fest",
                "producer_tenant": "owner-tenant",
                "status": "pending",
                "total_cents": 10000,
                "base_amount": None,
                "fee_amount": None,
                "total_amount": None,
                "items_json": None,
                "buyer_email": "buyer@example.com",
                "buyer_name": "Comprador Test",
            }
            return self
        if "from events" in q and "where tenant_id=%s and slug=%s" in q:
            self._next_fetchone = {
                "settlement_mode": "manual_transfer",
                "service_charge_pct": None,
            }
            return self
        return self

    def fetchone(self):
        value = self._next_fetchone
        self._next_fetchone = None
        return value

    def fetchall(self):
        value = self._next_fetchall
        self._next_fetchall = []
        return value


class _PreferenceConn:
    def __init__(self):
        self.cur = _PreferenceCursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cur

    def commit(self):
        return None


def test_mp_create_preference_does_not_select_missing_amount_columns(monkeypatch):
    conn = _PreferenceConn()

    def _fake_get_conn():
        return conn

    monkeypatch.setattr(payments_mp, "MP_ACCESS_TOKEN", "APP_USR-test-999")
    monkeypatch.setattr(payments_mp, "get_conn", _fake_get_conn)

    client = TestClient(app)
    resp = client.post(
        "/api/payments/mp/create-preference?tenant=default&dry_run=true",
        json={"order_id": "order-123"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["dry_run"] is True
    assert body["preference"]["items"][0]["unit_price"] == 115.0
    assert "base_amount" not in conn.cur.order_select_sql.replace("NULL::numeric AS base_amount", "")
    assert "fee_amount" not in conn.cur.order_select_sql.replace("NULL::numeric AS fee_amount", "")
    assert "total_amount" not in conn.cur.order_select_sql.replace("NULL::numeric AS total_amount", "")
