import json
import sqlite3
from datetime import datetime
from typing import Any

from app.core.logging import correlation_id_var


class AuditLog:
    """Append-only record of every HR-affecting action. Never updated,
    never deleted -- it's a record, not state, same reasoning as
    checkins_raw being append-only.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id TEXT NOT NULL,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                channel TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                details_json TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def record(
        self,
        actor_id: str,
        action: str,
        status: str,
        now: datetime,
        details: dict[str, Any] | None = None,
        channel: str = "api",
    ) -> None:
        # correlation_id is read from the same ContextVar the request
        # logging middleware sets (app/core/logging.py) -- callers don't
        # thread it through by hand, and it's "" outside a request (a
        # scheduled job, say), same fallback the log formatter uses.
        self._conn.execute(
            """
            INSERT INTO audit_log
                (actor_id, action, status, channel, correlation_id, details_json, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                actor_id,
                action,
                status,
                channel,
                correlation_id_var.get(),
                json.dumps(details or {}),
                now.isoformat(),
            ),
        )
        self._conn.commit()
