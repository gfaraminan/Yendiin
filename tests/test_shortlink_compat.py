from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_short_checkout_path_serves_spa_index():
    resp = client.get('/c?event=maria-split-2&bar=principal')
    assert resp.status_code == 200
    assert 'text/html' in (resp.headers.get('content-type') or '').lower()


def test_confirm_path_serves_spa_index():
    resp = client.get('/confirm?event=drcula&bar=principal&order_id=abc')
    assert resp.status_code == 200
    assert 'text/html' in (resp.headers.get('content-type') or '').lower()
