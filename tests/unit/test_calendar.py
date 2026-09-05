from datetime import date

from app.domain.calendar import COUNTRY_CALENDARS, is_working_day, working_days_between


def test_all_four_countries_have_a_calendar() -> None:
    assert set(COUNTRY_CALENDARS) == {"KSA", "UAE", "Egypt", "Jordan"}


def test_ksa_weekend_is_friday_saturday() -> None:
    calendar = COUNTRY_CALENDARS["KSA"]

    assert not is_working_day(calendar, date(2026, 9, 4))  # Friday
    assert not is_working_day(calendar, date(2026, 9, 5))  # Saturday
    assert is_working_day(calendar, date(2026, 9, 6))  # Sunday
    assert is_working_day(calendar, date(2026, 9, 7))  # Monday


def test_uae_weekend_is_saturday_sunday_not_friday_saturday() -> None:
    # Same week as the KSA test, different country -- this is the case
    # that breaks a single hardcoded "Gulf weekend" assumption.
    calendar = COUNTRY_CALENDARS["UAE"]

    assert is_working_day(calendar, date(2026, 9, 4))  # Friday: working in UAE
    assert not is_working_day(calendar, date(2026, 9, 5))  # Saturday
    assert not is_working_day(calendar, date(2026, 9, 6))  # Sunday


def test_holiday_on_an_ordinary_weekday_is_not_a_working_day() -> None:
    calendar = COUNTRY_CALENDARS["KSA"]

    # 2026-09-23 (KSA National Day) is a Wednesday -- would be a working
    # day by weekend rules alone, so this only passes if holidays are
    # actually checked, not just weekends.
    assert not is_working_day(calendar, date(2026, 9, 23))


def test_holiday_that_falls_on_a_weekend_does_not_break_the_count() -> None:
    # 2026-05-01 (Egypt Labour Day) is a Friday, already a weekend day --
    # the two conditions overlapping on the same day must not be
    # double-subtracted. Range: Wed 4/29, Thu 4/30, Fri 5/1 (weekend +
    # holiday), Sat 5/2 (weekend), Sun 5/3 -- 3 working days.
    calendar = COUNTRY_CALENDARS["Egypt"]

    days = working_days_between(calendar, date(2026, 4, 29), date(2026, 5, 3))

    assert days == 3


def test_working_days_between_excludes_weekends_and_holidays() -> None:
    calendar = COUNTRY_CALENDARS["KSA"]

    # 2026-09-20 (Sun) through 2026-09-24 (Thu): a full working week,
    # minus 2026-09-23 (Wed) which is National Day.
    days = working_days_between(calendar, date(2026, 9, 20), date(2026, 9, 24))

    assert days == 4


def test_working_days_between_is_inclusive_of_both_endpoints() -> None:
    calendar = COUNTRY_CALENDARS["KSA"]

    assert working_days_between(calendar, date(2026, 9, 6), date(2026, 9, 6)) == 1


def test_working_days_between_returns_zero_for_an_inverted_range() -> None:
    calendar = COUNTRY_CALENDARS["KSA"]

    assert working_days_between(calendar, date(2026, 9, 10), date(2026, 9, 1)) == 0
