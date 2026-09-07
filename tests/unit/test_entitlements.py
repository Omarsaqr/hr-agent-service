from datetime import date, timedelta

from app.domain.countries import COUNTRY_POLICIES, AnnualLeavePolicy, EntitlementTier
from app.domain.entitlements import (
    age_in_years,
    annual_leave_balance,
    annual_leave_entitlement,
    completed_months_of_service,
    current_leave_year_bounds,
)


def test_naive_year_subtraction_would_overcount_tenure_before_the_anniversary() -> None:
    # Hired 2021-11-01; checked two weeks before the fifth anniversary.
    # Naive `as_of.year - reference.year` gives 5 (2026 - 2021), which
    # would grant the 30-day KSA tier two weeks early. The correct answer
    # is 4 completed years -- the anniversary hasn't happened yet.
    hired = date(2021, 11, 1)
    just_before_anniversary = date(2026, 10, 15)

    months = completed_months_of_service(hired, just_before_anniversary)

    assert months == 4 * 12 + 11
    assert months // 12 == 4


def test_tenure_completes_exactly_on_the_anniversary_date() -> None:
    hired = date(2021, 11, 1)

    assert completed_months_of_service(hired, date(2026, 11, 1)) // 12 == 5


def test_completed_months_never_goes_negative_for_a_future_start_date() -> None:
    assert completed_months_of_service(date(2026, 1, 1), date(2025, 1, 1)) == 0


def test_age_in_years_uses_the_same_anniversary_logic() -> None:
    born = date(1990, 6, 15)

    assert age_in_years(born, date(2026, 6, 14)) == 35
    assert age_in_years(born, date(2026, 6, 15)) == 36


def test_ksa_entitlement_is_21_days_below_five_years_and_30_at_five_years() -> None:
    policy = COUNTRY_POLICIES["KSA"].annual_leave

    assert annual_leave_entitlement(policy, completed_months=59) == 21
    assert annual_leave_entitlement(policy, completed_months=60) == 30


def test_jordan_entitlement_is_14_days_below_five_years_and_21_at_five_years() -> None:
    policy = COUNTRY_POLICIES["Jordan"].annual_leave

    assert annual_leave_entitlement(policy, completed_months=59) == 14
    assert annual_leave_entitlement(policy, completed_months=60) == 21


def test_uae_entitlement_accrues_two_days_per_month_between_six_and_twelve_months() -> None:
    policy = COUNTRY_POLICIES["UAE"].annual_leave

    assert annual_leave_entitlement(policy, completed_months=5) == 0
    assert annual_leave_entitlement(policy, completed_months=8) == 4
    assert annual_leave_entitlement(policy, completed_months=12) == 30


def test_egypt_entitlement_steps_at_one_and_ten_years() -> None:
    policy = COUNTRY_POLICIES["Egypt"].annual_leave

    assert annual_leave_entitlement(policy, completed_months=6) == 15
    assert annual_leave_entitlement(policy, completed_months=12) == 21
    assert annual_leave_entitlement(policy, completed_months=120) == 30


def test_egypt_entitlement_reaches_the_top_tier_at_age_fifty_regardless_of_tenure() -> None:
    policy = COUNTRY_POLICIES["Egypt"].annual_leave

    assert annual_leave_entitlement(policy, completed_months=24, age=50) == 30
    assert annual_leave_entitlement(policy, completed_months=24, age=49) == 21


def test_age_alternative_does_not_skip_the_entry_tier_for_a_new_hire() -> None:
    # Age 50 is a substitute for the 10-year tenure test on the top tier,
    # not a substitute for having any service at all. A 52-year-old hired
    # three months ago hasn't reached the 1-year/21-day tier yet either,
    # so the age branch must not vault them past it to 30.
    policy = COUNTRY_POLICIES["Egypt"].annual_leave

    assert annual_leave_entitlement(policy, completed_months=3, age=52) == 15


def test_annual_leave_balance_is_entitlement_minus_taken() -> None:
    assert annual_leave_balance(entitlement_days=21, taken_days=3) == 18


def test_annual_leave_balance_can_go_negative_rather_than_clamp() -> None:
    # An over-drawn balance (e.g. after a tenure-tier or policy change)
    # is a real state worth surfacing, not one to hide behind a floor.
    assert annual_leave_balance(entitlement_days=14, taken_days=20) == -6


def test_current_leave_year_bounds_before_this_years_anniversary() -> None:
    hired = date(2021, 11, 1)

    assert current_leave_year_bounds(hired, date(2026, 10, 15)) == (
        date(2025, 11, 1),
        date(2026, 10, 31),
    )


def test_current_leave_year_bounds_on_the_anniversary_itself() -> None:
    hired = date(2021, 11, 1)

    assert current_leave_year_bounds(hired, date(2026, 11, 1)) == (
        date(2026, 11, 1),
        date(2027, 10, 31),
    )


def test_current_leave_year_bounds_after_this_years_anniversary() -> None:
    hired = date(2021, 11, 1)

    assert current_leave_year_bounds(hired, date(2026, 11, 2)) == (
        date(2026, 11, 1),
        date(2027, 10, 31),
    )


def test_current_leave_year_bounds_handles_a_leap_day_hire_date() -> None:
    hired = date(2020, 2, 29)

    # 2026 isn't a leap year, so the anniversary falls back to Feb 28;
    # by March 1 that anniversary has already passed this year. The next
    # one falls back the same way, to 2027-02-28, one day before which
    # closes out the leave year.
    assert current_leave_year_bounds(hired, date(2026, 3, 1)) == (
        date(2026, 2, 28),
        date(2027, 2, 27),
    )


def test_current_leave_year_bounds_end_excludes_a_request_dated_the_next_leave_year() -> None:
    # This is the property that actually matters for get_time_off_taken:
    # a date one day past `end` belongs to the *next* leave year, not
    # this one -- verified directly here, not just indirectly through
    # whatever HRISPort implementation happens to consume it.
    hired = date(2021, 11, 1)

    _, end = current_leave_year_bounds(hired, date(2026, 10, 15))

    assert end == date(2026, 10, 31)
    assert end + timedelta(days=1) == date(2026, 11, 1)  # the next anniversary


def test_a_flat_country_with_no_further_tiers_needs_no_code_change() -> None:
    # Demonstrates the "adding Oman is a data change" property directly:
    # a country with a single flat rate is just one tier, no branch in
    # annual_leave_entitlement cares that it has never seen "Oman" before.
    flat_policy = AnnualLeavePolicy(
        citation="Oman Labour Law, mock entry for this test",
        source_url="https://example.invalid/oman-labour-law",
        last_reviewed=date(2026, 9, 5),
        tiers=(EntitlementTier(min_months=0, annual_days=30),),
    )

    assert annual_leave_entitlement(flat_policy, completed_months=1) == 30
    assert annual_leave_entitlement(flat_policy, completed_months=240) == 30
