import ast
import importlib
from pathlib import Path


def test_producer_router_module_imports():
    module = importlib.import_module("app.routers.producer")
    assert module is not None


def test_producer_events_endpoint_exists():
    module = importlib.import_module("app.routers.producer")
    assert hasattr(module, "api_producer_events")


def test_producer_router_source_is_valid_python():
    source = Path("app/routers/producer.py").read_text(encoding="utf-8")
    ast.parse(source)
