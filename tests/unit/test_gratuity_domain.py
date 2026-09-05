from datetime import date

import pytest

from app.domain.entitlements import years_of_service
from app.domain.gratuity import egypt_retirement_gratuity, ksa_gratuity, uae_gratuity

# --- entitlements.years_of_service ------------------------------------------


def test_years_of_service_converts_completed_months_to_fractional_years() -> None:
    assert years_of_service(date(2020, 1, 1), date(2023, 7, 1)) == pytest.approx(3.5)


# --- KSA ----------------------------------------------------------------------


def test_ksa_termination_without_cause_pays_full_award_regardless_of_tenure() -> None:
    result = ksa_gratuity(10_000, 3, reason="termination")

    assert result.amount == pytest.approx(15_000)  # 3 * 0.5 * 10000
    assert result.basis == "ksa_full_award"


def test_ksa_retirement_and_death_or_disability_also_pay_full_award() -> None:
    for reason in ("retirement", "death_or_disability"):
        result = ksa_gratuity(10_000, 7, reason=reason)
        assert result.amount == pytest.approx(45_000)  # 5*0.5*10000 + 2*1*10000


def test_ksa_termination_for_cause_forfeits_everything() -> None:
    result = ksa_gratuity(10_000, 20, reason="termination_for_cause")

    assert result.amount == 0.0
    assert result.basis == "ksa_article_80_forfeited"


@pytest.mark.parametrize(
    "years,expected_multiplier",
    [(1.9, 0.0), (3, 1 / 3), (7, 2 / 3), (12, 1.0)],
)
def test_ksa_resignation_scales_by_tenure(years: float, expected_multiplier: float) -> None:
    result = ksa_gratuity(10_000, years, reason="resignation")
    base = ksa_gratuity(10_000, years, reason="termination").amount

    assert result.amount == pytest.approx(base * expected_multiplier)


# --- UAE ------------------------------------------------------------------


def test_uae_below_minimum_service_pays_nothing() -> None:
    result = uae_gratuity(9_000, 0.5)

    assert result.amount == 0.0
    assert result.basis == "uae_minimum_service_not_met"


def test_uae_standard_calculation_under_the_cap() -> None:
    result = uae_gratuity(9_000, 3)

    # daily_rate = 300; 3 years * 21 days * 300
    assert result.amount == pytest.approx(18_900)
    assert result.basis == "uae_standard"


def test_uae_second_tier_uses_thirty_days_per_year() -> None:
    result = uae_gratuity(9_000, 7)

    # 5*21*300 + 2*30*300 = 31500 + 18000
    assert result.amount == pytest.approx(49_500)


def test_uae_caps_at_two_years_salary_for_long_tenure() -> None:
    result = uae_gratuity(9_000, 30)

    assert result.amount == pytest.approx(9_000 * 24)
    assert result.basis == "uae_capped_at_two_years_salary"


# --- Egypt ------------------------------------------------------------------


def test_egypt_retirement_gratuity_two_tier_calculation() -> None:
    result = egypt_retirement_gratuity(8_000, 8)

    # 5*0.5*8000 + 3*1*8000 = 20000 + 24000
    assert result.amount == pytest.approx(44_000)
    assert result.basis == "egypt_retirement"
