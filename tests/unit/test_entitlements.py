from datetime import date

from app.domain.countries import COUNTRY_POLICIES, AnnualLeavePolicy, EntitlementTier
from app.domain.entitlements import (
    age_in_years,
    annual_leave_entitlement,
    completed_months_of_service,
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
