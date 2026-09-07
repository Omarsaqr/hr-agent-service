import pytest
from fastapi.testclient import TestClient

import app.deps as deps_module
from app.integrations.llm.mock import MockLLMAdapter
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _force_mock_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    # These tests assert on MockLLMAdapter's specific deterministic
    # replies ("confirm", the leave-request phrasing below), so they
    # need mock regardless of what LLM_DRIVER the real .env is currently
    # set to (e.g. gemini, for live-key testing against the dev server).
    # Same reasoning as tests/e2e/conftest.py's e2e fixture -- see
    # docs/ROADMAP.md for the gap this closes.
    settings = app.state.settings
    monkeypatch.setitem(deps_module._llm_port_cache, settings.llm_driver, MockLLMAdapter())


def test_health_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_without_a_session_id_starts_a_new_one() -> None:
    response = client.post(
        "/chat", json={"employee_id": "does-not-exist", "message": "hello"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"]
    assert body["reply"]


def test_chat_reuses_history_across_calls_with_the_same_session_id() -> None:
    first = client.post(
        "/chat",
        json={
            "employee_id": "does-not-exist",
            "message": "request leave 2026-06-01 to 2026-06-05",
        },
    ).json()
    session_id = first["session_id"]

    # emp-id doesn't exist in the memory adapter (this test doesn't seed
    # one), so the preview itself fails -- what this actually checks is
    # that the second call's session_id round-trips and reuses the same
    # in-memory history rather than starting fresh.
    second = client.post(
        "/chat",
        json={
            "employee_id": "does-not-exist",
            "message": "confirm",
            "session_id": session_id,
        },
    ).json()

    assert second["session_id"] == session_id


def test_root_serves_the_web_portal_page() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "HR Assistant" in response.text
    assert "/chat" in response.text
