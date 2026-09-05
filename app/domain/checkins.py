from dataclasses import dataclass
from datetime import date, timedelta

from app.domain.models import CheckinRecord

MIN_RATING = 1
MAX_RATING = 5


def is_valid_rating(rating: int) -> bool:
    return MIN_RATING <= rating <= MAX_RATING


def week_bounds(as_of: date) -> tuple[date, date]:
    """The Sunday-to-Saturday week containing as_of -- the Gulf work
    week, not the ISO (Monday-start) one. Verified against
    date.weekday()/strftime, not derived by hand: 2026-06-07 is a
    confirmed Sunday, and every day through 2026-06-13 (Saturday) maps
    back to it below.
    """
    days_since_sunday = (as_of.weekday() + 1) % 7
    start = as_of - timedelta(days=days_since_sunday)
    return start, start + timedelta(days=6)


def missing_employee_ids(expected_ids: list[str], checkins: list[CheckinRecord]) -> list[str]:
    submitted = {c.employee_id for c in checkins}
    return [employee_id for employee_id in expected_ids if employee_id not in submitted]


@dataclass(frozen=True, slots=True)
class TeamWeekSummary:
    week_start: date
    week_end: date
    expected_employee_ids: list[str]
    checkins: list[CheckinRecord]
    missing_employee_ids: list[str]
    average_rating: float | None


def summarize_team_week(
    expected_employee_ids: list[str],
    checkins: list[CheckinRecord],
    week_start: date,
    week_end: date,
) -> TeamWeekSummary:
    """checkins is expected to already be scoped to expected_employee_ids
    and [week_start, week_end] -- DashboardPort.get_checkins does that
    filtering (and "latest submission per day wins") at the adapter
    boundary, so this just aggregates what it's given rather than
    re-filtering it.
    """
    ratings = [c.rating for c in checkins]
    average = sum(ratings) / len(ratings) if ratings else None
    return TeamWeekSummary(
        week_start=week_start,
        week_end=week_end,
        expected_employee_ids=expected_employee_ids,
        checkins=checkins,
        missing_employee_ids=missing_employee_ids(expected_employee_ids, checkins),
        average_rating=average,
    )
