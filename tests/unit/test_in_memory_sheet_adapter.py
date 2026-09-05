from datetime import UTC, date, datetime

from app.domain.models import CheckinRecord
from app.integrations.sheets.memory import InMemorySheetAdapter


def make_checkin(**overrides: object) -> CheckinRecord:
    defaults: dict[str, object] = {
        "employee_id": "emp-1",
        "checkin_date": date(2026, 6, 1),
        "accomplishments": "shipped the report",
        "blockers": "none",
        "rating": 4,
        "submitted_by": "lead-1",
        "submitted_at": datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
        "idempotency_key": "key-1",
    }
    defaults.update(overrides)
    return CheckinRecord(**defaults)  # type: ignore[arg-type]


async def test_get_checkins_returns_appended_record_in_range() -> None:
    adapter = InMemorySheetAdapter()
    await adapter.append_checkin(make_checkin())

    result = await adapter.get_checkins(
        ["emp-1"], start=date(2026, 6, 1), end=date(2026, 6, 1)
    )

    assert len(result) == 1
    assert result[0].accomplishments == "shipped the report"


async def test_get_checkins_excludes_other_employees_and_dates() -> None:
    adapter = InMemorySheetAdapter()
    await adapter.append_checkin(make_checkin(employee_id="emp-2"))
    await adapter.append_checkin(make_checkin(checkin_date=date(2026, 6, 2)))

    result = await adapter.get_checkins(
        ["emp-1"], start=date(2026, 6, 1), end=date(2026, 6, 1)
    )

    assert result == []


async def test_resubmission_on_same_day_keeps_only_the_latest() -> None:
    adapter = InMemorySheetAdapter()
    await adapter.append_checkin(
        make_checkin(
            rating=3,
            submitted_at=datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
            idempotency_key="key-1",
        )
    )
    await adapter.append_checkin(
        make_checkin(
            rating=5,
            submitted_at=datetime(2026, 6, 1, 17, 0, tzinfo=UTC),
            idempotency_key="key-2",
        )
    )

    result = await adapter.get_checkins(
        ["emp-1"], start=date(2026, 6, 1), end=date(2026, 6, 1)
    )

    assert len(result) == 1
    assert result[0].rating == 5
