import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routers.payments_mp import _oauth_window_origin


class _Req:
    def __init__(self, origin=None):
        self.headers = {}
        if origin is not None:
            self.headers["origin"] = origin


def test_oauth_window_origin_accepts_https_origin():
    req = _Req("https://www.ticketpro.com.ar")
    assert _oauth_window_origin(req) == "https://www.ticketpro.com.ar"


def test_oauth_window_origin_rejects_invalid_values():
    assert _oauth_window_origin(_Req(None)) is None
    assert _oauth_window_origin(_Req("")) is None
    assert _oauth_window_origin(_Req("javascript:alert(1)")) is None
    assert _oauth_window_origin(_Req("not-a-url")) is None
