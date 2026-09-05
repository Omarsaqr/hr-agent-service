import asyncio
import logging
import random
from collections.abc import Awaitable, Callable

import httpx

logger = logging.getLogger("app.integrations.retry")

RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})
MAX_ATTEMPTS = 3
BASE_DELAY_SECONDS = 0.5
MAX_TOTAL_WAIT_SECONDS = 5.0


class UpstreamUnavailableError(Exception):
    """An upstream vendor is unreachable after retries, or a write's outcome is unknown."""


async def request_with_retry(
    send: Callable[[], Awaitable[httpx.Response]], *, idempotent: bool, service_name: str
) -> httpx.Response:
    """Send a request, retrying transient failures only.

    Shared across every vendor integration (BambooHR, Google Sheets) so
    retry/backoff policy is decided once, not reinvented per vendor.
    service_name is for error messages and logs only -- it doesn't change
    behavior.

    idempotent=False (any write) skips retrying network/timeout errors
    entirely -- a timeout after the request left this process means we
    don't know whether the vendor received it, and retrying risks applying
    it twice. An explicit 429/502/503/504 *response* is not ambiguous in
    the same way (the vendor never applied it), so those are retried
    regardless of idempotency.
    """
    total_waited = 0.0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = await send()
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            if not idempotent:
                raise UpstreamUnavailableError(
                    "network error on a non-idempotent request; not retrying"
                ) from exc
            if attempt == MAX_ATTEMPTS:
                raise UpstreamUnavailableError(f"{service_name} unreachable after retries") from exc
            total_waited = await _sleep_before_retry(
                service_name, attempt, total_waited, retry_after=None
            )
            continue

        if response.status_code not in RETRYABLE_STATUS_CODES:
            return response

        if attempt == MAX_ATTEMPTS:
            raise UpstreamUnavailableError(
                f"{service_name} returned {response.status_code} after {MAX_ATTEMPTS} attempts"
            )

        retry_after = _parse_retry_after(response.headers.get("Retry-After"))
        total_waited = await _sleep_before_retry(service_name, attempt, total_waited, retry_after)

    raise AssertionError("unreachable: loop above always returns or raises")


async def _sleep_before_retry(
    service_name: str, attempt: int, total_waited: float, retry_after: float | None
) -> float:
    if retry_after is not None:
        delay = retry_after
    else:
        delay = BASE_DELAY_SECONDS * (2 ** (attempt - 1))
        delay *= 1 + random.uniform(0, 0.25)  # jitter, +0-25%

    remaining_budget = MAX_TOTAL_WAIT_SECONDS - total_waited
    if delay > remaining_budget:
        # Truncating the wait and retrying anyway would likely just hit
        # the same 429/503 again -- a human is waiting on WhatsApp, so an
        # honest failure now beats a wait that doesn't match what the
        # server (or our own backoff) actually called for.
        raise UpstreamUnavailableError(f"{service_name} retry wait budget exhausted")

    logger.warning("retrying %s request: attempt %d, waiting %.2fs", service_name, attempt, delay)
    await asyncio.sleep(delay)
    return total_waited + delay


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        # HTTP-date form (RFC 7231) isn't parsed -- falls back to computed
        # backoff rather than guessing at a format vendors aren't
        # documented to send on their retryable endpoints.
        return None
