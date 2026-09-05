from datetime import UTC, datetime

from app.core.company_time import today_in_company_timezone


def test_late_utc_evening_is_already_the_next_day_in_riyadh() -> None:
    # 22:30 UTC is 01:30 the next day in Asia/Riyadh (UTC+3) -- this is
    # the exact boundary a write (submit_daily_checkin) and a read
    # (list_missing_checkins, get_team_summary) must agree on, or one
    # can report a just-submitted check-in as missing.
    late_utc = datetime(2026, 6, 8, 22, 30, tzinfo=UTC)

    assert today_in_company_timezone(late_utc) == datetime(2026, 6, 9).date()


def test_riyadh_morning_matches_utc_the_same_day() -> None:
    morning_utc = datetime(2026, 6, 8, 9, 0, tzinfo=UTC)

    assert today_in_company_timezone(morning_utc) == datetime(2026, 6, 8).date()
