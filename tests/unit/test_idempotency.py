import asyncio
import sqlite3
from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.idempotency import IdempotencyStore, compute_request_fingerprint

NOW = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def store() -> IdempotencyStore:
    return IdempotencyStore(sqlite3.connect(":memory:"))


def make_call_counter(
    result: dict[str, Any] | None = None,
) -> tuple[list[int], Any]:
    calls: list[int] = []

    async def work() -> dict[str, Any]:
        calls.append(1)
        return result or {"ok": True, "data": {"request_id": "req-1"}}

    return calls, work


async def test_first_call_runs_the_work_and_returns_its_response(
    store: IdempotencyStore,
) -> None:
    calls, work = make_call_counter()

    result = await store.run("key-1", "fingerprint-1", NOW, work)

    assert len(calls) == 1
    assert result == {"ok": True, "data": {"request_id": "req-1"}}


async def test_replay_returns_identical_response_without_calling_work_again(
    store: IdempotencyStore,
) -> None:
    calls, work = make_call_counter()

    first = await store.run("key-1", "fingerprint-1", NOW, work)
    second = await store.run("key-1", "fingerprint-1", NOW, work)

    assert len(calls) == 1  # work() was not invoked the second time
    assert second == first


async def test_concurrent_duplicates_exactly_one_does_the_work(
    store: IdempotencyStore,
) -> None:
    calls: list[int] = []

    async def work() -> dict[str, Any]:
        calls.append(1)
        # A real await point, so concurrent callers actually interleave
        # here rather than the whole thing resolving synchronously.
        await asyncio.sleep(0.01)
        return {"ok": True, "data": {"request_id": "req-1"}}

    results = await asyncio.gather(
        store.run("key-1", "fingerprint-1", NOW, work),
        store.run("key-1", "fingerprint-1", NOW, work),
        store.run("key-1", "fingerprint-1", NOW, work),
    )

    assert len(calls) == 1
    successes = [r for r in results if r.get("ok") is True]
    in_progress = [r for r in results if r.get("code") == "REQUEST_IN_PROGRESS"]
    assert len(successes) == 1
    assert len(in_progress) == 2


async def test_same_key_different_fingerprint_is_rejected(store: IdempotencyStore) -> None:
    calls, work = make_call_counter()
    await store.run("key-1", "fingerprint-1", NOW, work)

    other_calls, other_work = make_call_counter()
    result = await store.run("key-1", "fingerprint-2", NOW, other_work)

    assert result["ok"] is False
    assert result["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert len(other_calls) == 0  # never ran -- this is a rejection, not a replay


async def test_failure_path_leaves_no_row_behind(store: IdempotencyStore) -> None:
    async def failing_work() -> dict[str, Any]:
        raise RuntimeError("upstream exploded")

    with pytest.raises(RuntimeError, match="upstream exploded"):
        await store.run("key-1", "fingerprint-1", NOW, failing_work)

    row = store._conn.execute(
        "SELECT 1 FROM idempotency_keys WHERE idempotency_key = ?", ("key-1",)
    ).fetchone()
    assert row is None

    # A genuine retry with the same key must proceed normally, not be
    # treated as a replay or an in-progress duplicate.
    calls, work = make_call_counter()
    result = await store.run("key-1", "fingerprint-1", NOW, work)
    assert len(calls) == 1
    assert result["ok"] is True


def test_compute_request_fingerprint_is_deterministic() -> None:
    fp1 = compute_request_fingerprint("submit_leave_request", {"employee_id": "1", "days": 5})
    fp2 = compute_request_fingerprint("submit_leave_request", {"employee_id": "1", "days": 5})

    assert fp1 == fp2


def test_compute_request_fingerprint_differs_for_different_arguments() -> None:
    fp1 = compute_request_fingerprint("submit_leave_request", {"employee_id": "1", "days": 5})
    fp2 = compute_request_fingerprint("submit_leave_request", {"employee_id": "1", "days": 6})

    assert fp1 != fp2


def test_compute_request_fingerprint_is_order_independent() -> None:
    # Canonical JSON (sort_keys) means argument order in the caller's
    # dict can't accidentally produce two fingerprints for one request.
    fp1 = compute_request_fingerprint("tool", {"a": 1, "b": 2})
    fp2 = compute_request_fingerprint("tool", {"b": 2, "a": 1})

    assert fp1 == fp2
