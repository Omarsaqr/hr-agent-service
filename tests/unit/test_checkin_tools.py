import sqlite3
from datetime import UTC, date, datetime

import pytest

from app.api.tools.checkins import get_team_summary, list_missing_checkins, submit_daily_checkin
from app.core.audit import AuditLog
from app.core.idempotency import IdempotencyStore
from app.domain.models import CheckinRecord, Employee
from app.integrations.bamboohr.memory import InMemoryHRISAdapter
from app.integrations.sheets.memory import InMemorySheetAdapter

NOW = datetime(2026, 6, 8, 9, 0, tzinfo=UTC)  # a Monday


@pytest.fixture
def hris() -> InMemoryHRISAdapter:
    adapter = InMemoryHRISAdapter()
    adapter.seed_employee(
        Employee(
            employee_id="mgr-1",
            full_name="Manager One",
            country="KSA",
            employment_start_date=date(2015, 1, 1),
            status="active",
        )
    )
    adapter.seed_employee(
        Employee(
            employee_id="emp-1",
            full_name="Sara Ahmed",
            country="KSA",
            employment_start_date=date(2020, 1, 1),
            status="active",
            manager_id="mgr-1",
        )
    )
    adapter.seed_employee(
        Employee(
            employee_id="emp-2",
            full_name="Omar Khalid",
            country="KSA",
            employment_start_date=date(2020, 1, 1),
            status="active",
            manager_id="mgr-1",
        )
    )
    return adapter


@pytest.fixture
def dashboard() -> InMemorySheetAdapter:
    return InMemorySheetAdapter()


@pytest.fixture
def idempotency_store() -> IdempotencyStore:
    return IdempotencyStore(sqlite3.connect(":memory:"))


@pytest.fixture
def audit_log() -> AuditLog:
    return AuditLog(sqlite3.connect(":memory:"))


# --- submit_daily_checkin ---------------------------------------------------


async def test_submit_daily_checkin_records_it_and_audits_success(
    hris: InMemoryHRISAdapter,
    dashboard: InMemorySheetAdapter,
    idempotency_store: IdempotencyStore,
    audit_log: AuditLog,
) -> None:
    result = await submit_daily_checkin(
        "emp-1", "shipped the report", "none", 4, "idem-1",
        hris=hris, dashboard=dashboard, idempotency_store=idempotency_store,
        audit_log=audit_log, now=NOW,
    )

    assert result["ok"] is True
    assert result["data"]["checkin_date"] == "2026-06-08"
    stored = await dashboard.get_checkins(["emp-1"], date(2026, 6, 8), date(2026, 6, 8))
    assert len(stored) == 1
    assert stored[0].accomplishments == "shipped the report"
    audited = audit_log._conn.execute("SELECT status FROM audit_log").fetchall()
    assert audited == [("success",)]


async def test_submit_daily_checkin_unknown_employee(
    hris: InMemoryHRISAdapter,
    dashboard: InMemorySheetAdapter,
    idempotency_store: IdempotencyStore,
    audit_log: AuditLog,
) -> None:
    result = await submit_daily_checkin(
        "does-not-exist", "x", "y", 3, "idem-1",
        hris=hris, dashboard=dashboard, idempotency_store=idempotency_store,
        audit_log=audit_log, now=NOW,
    )

    assert result["ok"] is False
    assert result["code"] == "EMPLOYEE_NOT_FOUND"


@pytest.mark.parametrize("rating", [0, 6, -1])
async def test_submit_daily_checkin_rejects_out_of_range_rating(
    rating: int,
    hris: InMemoryHRISAdapter,
    dashboard: InMemorySheetAdapter,
    idempotency_store: IdempotencyStore,
    audit_log: AuditLog,
) -> None:
    result = await submit_daily_checkin(
        "emp-1", "x", "y", rating, "idem-1",
        hris=hris, dashboard=dashboard, idempotency_store=idempotency_store,
        audit_log=audit_log, now=NOW,
    )

    assert result["ok"] is False
    assert result["code"] == "INVALID_RATING"


async def test_submit_daily_checkin_uses_riyadh_local_date_not_utc_date(
    hris: InMemoryHRISAdapter,
    dashboard: InMemorySheetAdapter,
    idempotency_store: IdempotencyStore,
    audit_log: AuditLog,
) -> None:
    # 22:30 UTC is already 01:30 the next day in Asia/Riyadh (UTC+3) --
    # the stored checkin_date must reflect the company's local calendar,
    # not the UTC one the timestamp is expressed in.
    late_utc = datetime(2026, 6, 8, 22, 30, tzinfo=UTC)

    result = await submit_daily_checkin(
        "emp-1", "x", "y", 3, "idem-1",
        hris=hris, dashboard=dashboard, idempotency_store=idempotency_store,
        audit_log=audit_log, now=late_utc,
    )

    assert result["data"]["checkin_date"] == "2026-06-09"


async def test_submit_daily_checkin_replay_does_not_create_a_second_row(
    hris: InMemoryHRISAdapter,
    dashboard: InMemorySheetAdapter,
    idempotency_store: IdempotencyStore,
    audit_log: AuditLog,
) -> None:
    first = await submit_daily_checkin(
        "emp-1", "x", "y", 3, "idem-1",
        hris=hris, dashboard=dashboard, idempotency_store=idempotency_store,
        audit_log=audit_log, now=NOW,
    )
    second = await submit_daily_checkin(
        "emp-1", "x", "y", 3, "idem-1",
        hris=hris, dashboard=dashboard, idempotency_store=idempotency_store,
        audit_log=audit_log, now=NOW,
    )

    assert second == first
    stored = await dashboard.get_checkins(["emp-1"], date(2026, 6, 8), date(2026, 6, 8))
    assert len(stored) == 1


async def test_submit_daily_checkin_reused_key_with_different_content_is_rejected(
    hris: InMemoryHRISAdapter,
    dashboard: InMemorySheetAdapter,
    idempotency_store: IdempotencyStore,
    audit_log: AuditLog,
) -> None:
    await submit_daily_checkin(
        "emp-1", "x", "y", 3, "idem-1",
        hris=hris, dashboard=dashboard, idempotency_store=idempotency_store,
        audit_log=audit_log, now=NOW,
    )

    result = await submit_daily_checkin(
        "emp-1", "different accomplishment", "y", 3, "idem-1",
        hris=hris, dashboard=dashboard, idempotency_store=idempotency_store,
        audit_log=audit_log, now=NOW,
    )

    assert result["ok"] is False
    assert result["code"] == "IDEMPOTENCY_KEY_REUSED"


# --- list_missing_checkins ---------------------------------------------------


async def test_list_missing_checkins_lists_those_who_have_not_submitted_today(
    hris: InMemoryHRISAdapter, dashboard: InMemorySheetAdapter
) -> None:
    await dashboard.append_checkin(
        CheckinRecord(
            employee_id="emp-1",
            checkin_date=date(2026, 6, 8),
            accomplishments="x",
            blockers="",
            rating=4,
            submitted_by="emp-1",
            submitted_at=NOW,
            idempotency_key="key-1",
        )
    )

    result = await list_missing_checkins(
        "mgr-1", hris=hris, dashboard=dashboard, as_of=date(2026, 6, 8)
    )

    assert result["ok"] is True
    assert [m["employee_id"] for m in result["data"]["missing_employees"]] == ["emp-2"]
    assert result["data"]["missing_employees"][0]["full_name"] == "Omar Khalid"


async def test_list_missing_checkins_empty_when_everyone_submitted(
    hris: InMemoryHRISAdapter, dashboard: InMemorySheetAdapter
) -> None:
    for employee_id in ("emp-1", "emp-2"):
        await dashboard.append_checkin(
            CheckinRecord(
                employee_id=employee_id,
                checkin_date=date(2026, 6, 8),
                accomplishments="x",
                blockers="",
                rating=4,
                submitted_by=employee_id,
                submitted_at=NOW,
                idempotency_key=f"key-{employee_id}",
            )
        )

    result = await list_missing_checkins(
        "mgr-1", hris=hris, dashboard=dashboard, as_of=date(2026, 6, 8)
    )

    assert result["data"]["missing_employees"] == []


async def test_list_missing_checkins_unknown_manager(
    hris: InMemoryHRISAdapter, dashboard: InMemorySheetAdapter
) -> None:
    result = await list_missing_checkins(
        "does-not-exist", hris=hris, dashboard=dashboard, as_of=date(2026, 6, 8)
    )

    assert result["ok"] is False
    assert result["code"] == "EMPLOYEE_NOT_FOUND"


# --- get_team_summary --------------------------------------------------------


async def test_get_team_summary_computes_average_rating_and_missing(
    hris: InMemoryHRISAdapter, dashboard: InMemorySheetAdapter
) -> None:
    await dashboard.append_checkin(
        CheckinRecord(
            employee_id="emp-1",
            checkin_date=date(2026, 6, 8),
            accomplishments="shipped x",
            blockers="none",
            rating=4,
            submitted_by="emp-1",
            submitted_at=NOW,
            idempotency_key="key-1",
        )
    )

    result = await get_team_summary(
        "mgr-1", hris=hris, dashboard=dashboard, as_of=date(2026, 6, 10)
    )

    assert result["ok"] is True
    assert result["data"]["week_start"] == "2026-06-07"
    assert result["data"]["week_end"] == "2026-06-13"
    assert result["data"]["expected_count"] == 2
    assert result["data"]["submitted_count"] == 1
    assert result["data"]["average_rating"] == 4.0
    assert [m["employee_id"] for m in result["data"]["missing_employees"]] == ["emp-2"]
    assert len(result["data"]["checkins"]) == 1


async def test_get_team_summary_with_no_submissions_has_no_average(
    hris: InMemoryHRISAdapter, dashboard: InMemorySheetAdapter
) -> None:
    result = await get_team_summary(
        "mgr-1", hris=hris, dashboard=dashboard, as_of=date(2026, 6, 10)
    )

    assert result["data"]["average_rating"] is None
    assert result["data"]["submitted_count"] == 0


async def test_get_team_summary_manager_with_no_direct_reports(
    hris: InMemoryHRISAdapter, dashboard: InMemorySheetAdapter
) -> None:
    result = await get_team_summary(
        "emp-1", hris=hris, dashboard=dashboard, as_of=date(2026, 6, 10)
    )

    assert result["ok"] is True
    assert result["data"]["expected_count"] == 0
    assert result["data"]["missing_employees"] == []


async def test_get_team_summary_unknown_manager(
    hris: InMemoryHRISAdapter, dashboard: InMemorySheetAdapter
) -> None:
    result = await get_team_summary(
        "does-not-exist", hris=hris, dashboard=dashboard, as_of=date(2026, 6, 10)
    )

    assert result["ok"] is False
    assert result["code"] == "EMPLOYEE_NOT_FOUND"
