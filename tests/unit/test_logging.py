import json
import logging

from fastapi.testclient import TestClient

from app.core.logging import JsonFormatter, correlation_id_var
from app.main import app

client = TestClient(app)


def test_json_formatter_includes_correlation_id() -> None:
    token = correlation_id_var.set("test-correlation-id")
    try:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        formatted = JsonFormatter().format(record)
    finally:
        correlation_id_var.reset(token)

    payload = json.loads(formatted)
    assert payload["message"] == "hello world"
    assert payload["correlation_id"] == "test-correlation-id"
    assert payload["level"] == "INFO"


def test_health_response_carries_a_correlation_id() -> None:
    response = client.get("/health")

    assert "x-correlation-id" in response.headers


def test_supplied_correlation_id_is_echoed_back() -> None:
    response = client.get("/health", headers={"X-Correlation-Id": "abc-123"})

    assert response.headers["x-correlation-id"] == "abc-123"
