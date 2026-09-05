from datetime import UTC, date, datetime

from app.domain.checkins import (
    is_valid_rating,
    missing_employee_ids,
    summarize_team_week,
    week_bounds,
)
from app.domain.models import CheckinRecord


def make_checkin(**overrides: object) -> CheckinRecord:
    defaults: dict[str, object] = {
        "employee_id": "emp-1",
        "checkin_date": date(2026, 6, 8),
        "accomplishments": "shipped the report",
        "blockers": "none",
        "rating": 4,
        "submitted_by": "emp-1",
        "submitted_at": datetime(2026, 6, 8, 9, 0, tzinfo=UTC),
        "idempotency_key": "key-1",
    }
    defaults.update(overrides)
    return CheckinRecord(**defaults)  # type: ignore[arg-type]


def test_rating_bounds_are_inclusive() -> None:
    assert is_valid_rating(1) is True
    assert is_valid_rating(5) is True
    assert is_valid_rating(0) is False
    assert is_valid_rating(6) is False


def test_week_bounds_for_every_day_of_a_known_week() -> None:
    # 2026-06-07 is a confirmed Sunday (verified via date.strftime, not
    # hand-derived) -- every day through Saturday 2026-06-13 must map
    # back to the same (start, end) pair.
    expected = (date(2026, 6, 7), date(2026, 6, 13))
    for day in range(7):
        as_of = date(2026, 6, 7 + day)
        assert week_bounds(as_of) == expected, as_of


def test_week_bounds_for_a_monday_lands_on_the_prior_sunday() -> None:
    assert week_bounds(date(2026, 6, 1)) == (date(2026, 5, 31), date(2026, 6, 6))


def test_missing_employee_ids_excludes_those_who_submitted() -> None:
    checkins = [make_checkin(employee_id="emp-1"), make_checkin(employee_id="emp-2")]

    missing = missing_employee_ids(["emp-1", "emp-2", "emp-3"], checkins)

    assert missing == ["emp-3"]


def test_missing_employee_ids_preserves_expected_order() -> None:
    checkins = [make_checkin(employee_id="emp-2")]

    missing = missing_employee_ids(["emp-3", "emp-1", "emp-2"], checkins)

    assert missing == ["emp-3", "emp-1"]


def test_summarize_team_week_computes_average_and_missing() -> None:
    checkins = [
        make_checkin(employee_id="emp-1", rating=4),
        make_checkin(employee_id="emp-2", rating=2),
    ]

    summary = summarize_team_week(
        ["emp-1", "emp-2", "emp-3"], checkins, date(2026, 6, 7), date(2026, 6, 13)
    )

    assert summary.missing_employee_ids == ["emp-3"]
    assert summary.average_rating == 3.0
    assert summary.week_start == date(2026, 6, 7)
    assert summary.week_end == date(2026, 6, 13)


def test_summarize_team_week_average_is_none_with_no_submissions() -> None:
    summary = summarize_team_week(["emp-1"], [], date(2026, 6, 7), date(2026, 6, 13))

    assert summary.average_rating is None
    assert summary.missing_employee_ids == ["emp-1"]
