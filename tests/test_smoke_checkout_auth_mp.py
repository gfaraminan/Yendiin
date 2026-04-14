from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_public_config_exposes_high_risk_flags():
    resp = client.get('/api/public/config')
    assert resp.status_code == 200
    payload = resp.json()
    assert 'features' in payload
    assert 'altCheckoutUx' in payload['features']
    assert 'altProducerUi' in payload['features']
    assert 'altStaffUi' in payload['features']


def test_auth_me_endpoint_smoke():
    resp = client.get('/api/auth/me')
    assert resp.status_code in (200, 401)
