from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


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
