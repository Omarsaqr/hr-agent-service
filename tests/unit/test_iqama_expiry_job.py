import sqlite3
from datetime import UTC, date, datetime

import pytest

from app.core.iqama_alerts import IqamaAlertLog
from app.domain.models import Employee
from app.integrations.bamboohr.memory import InMemoryHRISAdapter
from app.jobs.iqama_expiry import run_iqama_expiry_check

AS_OF = date(2026, 6, 1)
NOW = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def alert_log() -> IqamaAlertLog:
    return IqamaAlertLog(sqlite3.connect(":memory:"))


async def test_flags_an_iqama_expiring_within_the_window(alert_log: IqamaAlertLog) -> None:
    hris = InMemoryHRISAdapter()
    hris.seed_employee(
        Employee(
            employee_id="emp-1",
            full_name="Sara Ahmed",
            country="KSA",
            employment_start_date=date(2020, 1, 1),
            status="active",
            iqama_expiry_date=date(2026, 8, 1),  # 61 days out
        )
    )

    alerts = await run_iqama_expiry_check(hris=hris, alert_log=alert_log, as_of=AS_OF, now=NOW)

    assert len(alerts) == 1
    assert alerts[0]["employee_id"] == "emp-1"
    assert alerts[0]["days_remaining"] == 61
    row = alert_log._conn.execute("SELECT employee_id, days_remaining FROM iqama_alerts").fetchone()
    assert row == ("emp-1", 61)


async def test_does_not_flag_an_iqama_far_from_expiry(alert_log: IqamaAlertLog) -> None:
    hris = InMemoryHRISAdapter()
    hris.seed_employee(
        Employee(
            employee_id="emp-1",
            full_name="Sara Ahmed",
            country="KSA",
            employment_start_date=date(2020, 1, 1),
            status="active",
            iqama_expiry_date=date(2027, 6, 1),  # a year out
        )
    )

    alerts = await run_iqama_expiry_check(hris=hris, alert_log=alert_log, as_of=AS_OF, now=NOW)

    assert alerts == []


async def test_flags_an_already_expired_iqama(alert_log: IqamaAlertLog) -> None:
    hris = InMemoryHRISAdapter()
    hris.seed_employee(
        Employee(
            employee_id="emp-1",
            full_name="Sara Ahmed",
            country="KSA",
            employment_start_date=date(2020, 1, 1),
            status="active",
            iqama_expiry_date=date(2026, 5, 1),
        )
    )

    alerts = await run_iqama_expiry_check(hris=hris, alert_log=alert_log, as_of=AS_OF, now=NOW)

    assert len(alerts) == 1
    assert alerts[0]["days_remaining"] < 0


async def test_ignores_employees_with_no_iqama_expiry_date_recorded(
    alert_log: IqamaAlertLog,
) -> None:
    hris = InMemoryHRISAdapter()
    hris.seed_employee(
        Employee(
            employee_id="emp-1",
            full_name="Sara Ahmed",
            country="KSA",
            employment_start_date=date(2020, 1, 1),
            status="active",
        )
    )

    assert await run_iqama_expiry_check(hris=hris, alert_log=alert_log, as_of=AS_OF, now=NOW) == []


async def test_ignores_non_ksa_employees_even_with_an_expiry_date(
    alert_log: IqamaAlertLog,
) -> None:
    hris = InMemoryHRISAdapter()
    hris.seed_employee(
        Employee(
            employee_id="emp-1",
            full_name="Omar Khalid",
            country="UAE",
            employment_start_date=date(2020, 1, 1),
            status="active",
            iqama_expiry_date=date(2026, 6, 5),
        )
    )

    assert await run_iqama_expiry_check(hris=hris, alert_log=alert_log, as_of=AS_OF, now=NOW) == []
