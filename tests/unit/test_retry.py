import httpx
import pytest
import respx

from app.integrations.retry import UpstreamUnavailableError, request_with_retry

BASE_URL = "https://api.example.test/v1"


@pytest.fixture
def sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    calls: list[float] = []

    async def recording_sleep(seconds: float) -> None:
        calls.append(seconds)

    monkeypatch.setattr("app.integrations.retry.asyncio.sleep", recording_sleep)
    return calls


@respx.mock
async def test_retries_a_503_and_then_succeeds(sleep_calls: list[float]) -> None:
    route = respx.get(f"{BASE_URL}/ping").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": True})]
    )

    async with httpx.AsyncClient() as client:
        response = await request_with_retry(
            lambda: client.get(f"{BASE_URL}/ping"), idempotent=True, service_name="test-service"
        )

    assert response.status_code == 200
    assert route.call_count == 2


@respx.mock
async def test_does_not_retry_a_plain_400(sleep_calls: list[float]) -> None:
    route = respx.get(f"{BASE_URL}/ping").mock(return_value=httpx.Response(400))

    async with httpx.AsyncClient() as client:
        response = await request_with_retry(
            lambda: client.get(f"{BASE_URL}/ping"), idempotent=True, service_name="test-service"
        )

    assert response.status_code == 400
    assert route.call_count == 1
    assert sleep_calls == []


@respx.mock
async def test_exhausts_attempts_and_raises_on_persistent_503(sleep_calls: list[float]) -> None:
    route = respx.get(f"{BASE_URL}/ping").mock(return_value=httpx.Response(503))

    async with httpx.AsyncClient() as client:
        with pytest.raises(UpstreamUnavailableError):
            await request_with_retry(
                lambda: client.get(f"{BASE_URL}/ping"),
                idempotent=True,
                service_name="test-service",
            )

    assert route.call_count == 3


@respx.mock
async def test_timeout_on_a_write_is_not_retried(sleep_calls: list[float]) -> None:
    route = respx.post(f"{BASE_URL}/ping").mock(side_effect=httpx.ConnectTimeout("boom"))

    async with httpx.AsyncClient() as client:
        with pytest.raises(UpstreamUnavailableError):
            await request_with_retry(
                lambda: client.post(f"{BASE_URL}/ping"),
                idempotent=False,
                service_name="test-service",
            )

    # Exactly one attempt: retrying an ambiguous network error on a write
    # risks applying it twice, so this must not touch the network again.
    assert route.call_count == 1
    assert sleep_calls == []


@respx.mock
async def test_timeout_on_a_read_is_retried(sleep_calls: list[float]) -> None:
    route = respx.get(f"{BASE_URL}/ping").mock(
        side_effect=[httpx.ConnectTimeout("boom"), httpx.Response(200, json={"ok": True})]
    )

    async with httpx.AsyncClient() as client:
        response = await request_with_retry(
            lambda: client.get(f"{BASE_URL}/ping"), idempotent=True, service_name="test-service"
        )

    assert response.status_code == 200
    assert route.call_count == 2


@respx.mock
async def test_honours_retry_after_header(sleep_calls: list[float]) -> None:
    respx.get(f"{BASE_URL}/ping").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    async with httpx.AsyncClient() as client:
        await request_with_retry(
            lambda: client.get(f"{BASE_URL}/ping"), idempotent=True, service_name="test-service"
        )

    assert sleep_calls == [2.0]


@respx.mock
async def test_retry_after_beyond_the_wait_budget_fails_fast_without_sleeping(
    sleep_calls: list[float],
) -> None:
    route = respx.get(f"{BASE_URL}/ping").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "30"})
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(UpstreamUnavailableError):
            await request_with_retry(
                lambda: client.get(f"{BASE_URL}/ping"),
                idempotent=True,
                service_name="test-service",
            )

    assert route.call_count == 1
    assert sleep_calls == []


@respx.mock
async def test_error_message_identifies_which_service_failed() -> None:
    # Shared across every vendor integration -- the service_name in the
    # error is what makes a failure log tell BambooHR and Google Sheets
    # apart without either adapter needing its own error type.
    respx.get(f"{BASE_URL}/ping").mock(return_value=httpx.Response(503))

    async with httpx.AsyncClient() as client:
        with pytest.raises(UpstreamUnavailableError, match="Google Sheets"):
            await request_with_retry(
                lambda: client.get(f"{BASE_URL}/ping"),
                idempotent=True,
                service_name="Google Sheets",
            )
