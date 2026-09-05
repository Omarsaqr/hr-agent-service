import hashlib
import json
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Any

from app.core.errors import ToolError

NONCE_RETENTION = timedelta(hours=1)
IDEMPOTENCY_RETENTION = timedelta(hours=24)


def _purge_expired(
    connection: sqlite3.Connection, table: str, timestamp_column: str, cutoff: datetime
) -> None:
    query = f"DELETE FROM {table} WHERE {timestamp_column} < ?"  # noqa: S608 -- table is a literal, not input
    connection.execute(query, (cutoff.isoformat(),))
    connection.commit()


class NonceStore:
    """Records consumed preview-token nonces (see core/preview_tokens.py).

    Lives alongside IdempotencyStore rather than in its own module: both
    are single-use-key-over-SQLite stores with the same lazy-cleanup
    shape, and one storage module doing it one way beats two doing it
    two slightly different ways.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS consumed_preview_nonces (
                nonce TEXT PRIMARY KEY,
                consumed_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def consume(self, nonce: str, now: datetime) -> bool:
        """Returns True the first time a nonce is seen, False on reuse."""
        _purge_expired(self._conn, "consumed_preview_nonces", "consumed_at", now - NONCE_RETENTION)
        try:
            self._conn.execute(
                "INSERT INTO consumed_preview_nonces (nonce, consumed_at) VALUES (?, ?)",
                (nonce, now.isoformat()),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


class _BeginOutcome(Enum):
    STARTED = auto()
    REPLAY = auto()
    IN_PROGRESS = auto()
    KEY_REUSED = auto()


@dataclass(frozen=True, slots=True)
class _BeginResult:
    outcome: _BeginOutcome
    response: dict[str, Any] | None = None


class IdempotencyStore:
    """Backs every mutating tool's idempotency_key. The PRIMARY KEY
    constraint on idempotency_key is what makes concurrent duplicates
    safe -- only one INSERT can win, everything else is a read of
    whatever the winner is doing.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS idempotency_keys (
                idempotency_key TEXT PRIMARY KEY,
                request_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                response_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    async def run(
        self,
        idempotency_key: str,
        request_fingerprint: str,
        now: datetime,
        work: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Runs work() at most once per idempotency_key.

        - First call: does the work, stores the response, returns it.
        - Replay (same key and fingerprint, already completed): returns
          the stored response verbatim -- work() is not called again.
        - Concurrent duplicate (same key, still in progress): returns
          REQUEST_IN_PROGRESS immediately rather than waiting.
        - Reused key (same key, different fingerprint): returns
          IDEMPOTENCY_KEY_REUSED -- a client bug, not a replay.
        - If work() raises, the row is deleted so a genuine retry with
          the same key can proceed, and the exception propagates --
          idempotency doesn't know how to turn an upstream failure into
          a tool error, only the caller does.
        """
        begin = self._begin(idempotency_key, request_fingerprint, now)

        if begin.outcome == _BeginOutcome.REPLAY:
            assert begin.response is not None
            return begin.response

        if begin.outcome == _BeginOutcome.IN_PROGRESS:
            return ToolError(
                code="REQUEST_IN_PROGRESS",
                message_en="This request is already being processed.",
                message_ar="هذا الطلب قيد المعالجة بالفعل.",
                recovery_hint="Wait a few seconds and retry with the same idempotency key.",
            ).to_response()

        if begin.outcome == _BeginOutcome.KEY_REUSED:
            return ToolError(
                code="IDEMPOTENCY_KEY_REUSED",
                message_en="This idempotency key was already used for a different request.",
                message_ar="تم استخدام مفتاح idempotency هذا بالفعل لطلب مختلف.",
                recovery_hint="Generate a new idempotency key for each distinct request.",
                data={"idempotency_key": idempotency_key},
            ).to_response()

        try:
            response = await work()
        except Exception:
            self._abort(idempotency_key)
            raise

        self._complete(idempotency_key, response)
        return response

    def _begin(self, idempotency_key: str, request_fingerprint: str, now: datetime) -> _BeginResult:
        _purge_expired(self._conn, "idempotency_keys", "created_at", now - IDEMPOTENCY_RETENTION)
        try:
            self._conn.execute(
                """
                INSERT INTO idempotency_keys
                    (idempotency_key, request_fingerprint, status, response_json, created_at)
                VALUES (?, ?, 'in_progress', NULL, ?)
                """,
                (idempotency_key, request_fingerprint, now.isoformat()),
            )
            self._conn.commit()
            return _BeginResult(_BeginOutcome.STARTED)
        except sqlite3.IntegrityError:
            pass

        row = self._conn.execute(
            "SELECT request_fingerprint, status, response_json FROM idempotency_keys "
            "WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        existing_fingerprint, status, response_json = row

        if existing_fingerprint != request_fingerprint:
            return _BeginResult(_BeginOutcome.KEY_REUSED)
        if status == "completed":
            return _BeginResult(_BeginOutcome.REPLAY, response=json.loads(response_json))
        return _BeginResult(_BeginOutcome.IN_PROGRESS)

    def _complete(self, idempotency_key: str, response: dict[str, Any]) -> None:
        self._conn.execute(
            "UPDATE idempotency_keys SET status = 'completed', response_json = ? "
            "WHERE idempotency_key = ?",
            (json.dumps(response), idempotency_key),
        )
        self._conn.commit()

    def _abort(self, idempotency_key: str) -> None:
        self._conn.execute(
            "DELETE FROM idempotency_keys WHERE idempotency_key = ?", (idempotency_key,)
        )
        self._conn.commit()


def compute_request_fingerprint(tool_name: str, arguments: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"tool": tool_name, "arguments": arguments}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
