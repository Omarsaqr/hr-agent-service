import sqlite3
from datetime import date, datetime


class IqamaAlertLog:
    """Every Iqama expiry that entered the alert window -- append-only,
    same shape as GapLog and AuditLog. This is the alert: there is no
    outbound messaging integration (WhatsApp/HeyLua) in this system, so
    "alerting" means recording it here for HR to review, not sending
    anyone a message.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS iqama_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id TEXT NOT NULL,
                full_name TEXT NOT NULL,
                expiry_date TEXT NOT NULL,
                days_remaining INTEGER NOT NULL,
                recorded_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def record(
        self,
        employee_id: str,
        full_name: str,
        expiry_date: date,
        days_remaining: int,
        now: datetime,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO iqama_alerts
                (employee_id, full_name, expiry_date, days_remaining, recorded_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (employee_id, full_name, expiry_date.isoformat(), days_remaining, now.isoformat()),
        )
        self._conn.commit()
