import sqlite3
from datetime import datetime


class GapLog:
    """Every question with no matching SOP -- this is the thing that
    makes "no answer" a signal instead of a dead end. HR reviewing this
    table is how the corpus actually grows.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sop_gaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                employee_id TEXT NOT NULL,
                country TEXT,
                channel TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def record(
        self,
        question: str,
        employee_id: str,
        country: str | None,
        now: datetime,
        channel: str = "api",
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO sop_gaps (question, employee_id, country, channel, recorded_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (question, employee_id, country, channel, now.isoformat()),
        )
        self._conn.commit()
