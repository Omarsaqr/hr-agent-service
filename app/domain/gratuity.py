from dataclasses import dataclass
from typing import Literal

# KSA (Saudi Labour Law, Royal Decree No. M/51):
#  - Art. 84: half a month's wage per year for the first 5 years, a full
#    month's wage per year after that.
#  - Art. 85: resigning voluntarily scales the award down by tenure.
#  - Art. 80: nine listed grounds for cause-termination forfeit it
#    entirely; anything else (employer termination without cause,
#    retirement, death, disability, force majeure under Art. 87) pays
#    the full award regardless of tenure.
KSA_TIER_1_YEARS = 5.0
KSA_TIER_1_MONTHLY_FRACTION = 0.5
KSA_TIER_2_MONTHLY_FRACTION = 1.0

# UAE (Federal Decree-Law No. 33 of 2021, Art. 51):
#  - 21 days' wage per year for the first 5 years, 30 days/year after.
#  - Capped at two years' total wage.
#  - Unlike the pre-2022 law, this is NOT reason-dependent: resignation,
#    ordinary termination, and even Art. 44 summary dismissal for gross
#    misconduct all pay the same award once the 1-year minimum is met.
#    Forfeiture for cause now requires a court ruling or MOHRE-approved
#    settlement -- something this system has no way to know about, so
#    it's never assumed here.
UAE_TIER_1_YEARS = 5.0
UAE_TIER_1_DAYS_PER_YEAR = 21.0
UAE_TIER_2_DAYS_PER_YEAR = 30.0
UAE_CAP_YEARS_OF_SALARY = 2.0
UAE_MINIMUM_YEARS_OF_SERVICE = 1.0

# Egypt (Labour Law No. 14 of 2025): Egypt has no Gulf-style gratuity
# payable on any separation -- end-of-service normally runs through the
# social-insurance/pension system (Law 148/2019), entirely outside this
# system's scope. The one figure with a confident, consistent citation
# is the retirement gratuity below; resignation and employer-initiated
# termination are governed by separate compensation formulas that
# depend on *why* the employer ended the contract (arbitrary dismissal,
# economic dismissal, fixed-term expiry), which secondary sources
# describe inconsistently enough that encoding them here risks stating
# a wrong severance figure with false confidence -- see ROADMAP.md.
EGYPT_TIER_1_YEARS = 5.0
EGYPT_TIER_1_MONTHLY_FRACTION = 0.5
EGYPT_TIER_2_MONTHLY_FRACTION = 1.0

SeparationReason = Literal[
    "resignation", "termination", "termination_for_cause", "retirement", "death_or_disability"
]


@dataclass(frozen=True, slots=True)
class GratuityResult:
    amount: float
    basis: str
    citation: str


def ksa_gratuity(
    basic_salary: float, years_of_service: float, reason: SeparationReason
) -> GratuityResult:
    citation = "Saudi Labour Law (Royal Decree No. M/51), Arts. 80, 84, 85, 87"

    if reason == "termination_for_cause":
        return GratuityResult(0.0, "ksa_article_80_forfeited", citation)

    base = _ksa_base_award(basic_salary, years_of_service)

    if reason == "resignation":
        multiplier = _ksa_resignation_multiplier(years_of_service)
        basis = f"ksa_resignation_multiplier_{multiplier:.3f}"
        return GratuityResult(base * multiplier, basis, citation)

    # termination (without cause), retirement, and death_or_disability
    # all pay the full award -- Arts. 84/87 don't distinguish between them.
    return GratuityResult(base, "ksa_full_award", citation)


def _ksa_base_award(basic_salary: float, years_of_service: float) -> float:
    tier_1_years = min(years_of_service, KSA_TIER_1_YEARS)
    tier_2_years = max(years_of_service - KSA_TIER_1_YEARS, 0.0)
    return (
        tier_1_years * KSA_TIER_1_MONTHLY_FRACTION * basic_salary
        + tier_2_years * KSA_TIER_2_MONTHLY_FRACTION * basic_salary
    )


def _ksa_resignation_multiplier(years_of_service: float) -> float:
    if years_of_service < 2:
        return 0.0
    if years_of_service < 5:
        return 1 / 3
    if years_of_service < 10:
        return 2 / 3
    return 1.0


def uae_gratuity(basic_salary: float, years_of_service: float) -> GratuityResult:
    """Reason-independent -- see the UAE_* constants' comment above."""
    citation = "UAE Federal Decree-Law No. 33 of 2021, Art. 51"

    if years_of_service < UAE_MINIMUM_YEARS_OF_SERVICE:
        return GratuityResult(0.0, "uae_minimum_service_not_met", citation)

    daily_rate = basic_salary / 30.0
    tier_1_years = min(years_of_service, UAE_TIER_1_YEARS)
    tier_2_years = max(years_of_service - UAE_TIER_1_YEARS, 0.0)
    uncapped = (
        tier_1_years * UAE_TIER_1_DAYS_PER_YEAR * daily_rate
        + tier_2_years * UAE_TIER_2_DAYS_PER_YEAR * daily_rate
    )
    cap = basic_salary * 12.0 * UAE_CAP_YEARS_OF_SALARY

    if uncapped > cap:
        return GratuityResult(cap, "uae_capped_at_two_years_salary", citation)
    return GratuityResult(uncapped, "uae_standard", citation)


def egypt_retirement_gratuity(basic_salary: float, years_of_service: float) -> GratuityResult:
    """Retirement only -- see the EGYPT_* constants' comment above for why
    resignation and employer termination aren't modelled here."""
    citation = "Egyptian Labour Law No. 14 of 2025 (retirement gratuity provisions)"
    tier_1_years = min(years_of_service, EGYPT_TIER_1_YEARS)
    tier_2_years = max(years_of_service - EGYPT_TIER_1_YEARS, 0.0)
    amount = (
        tier_1_years * EGYPT_TIER_1_MONTHLY_FRACTION * basic_salary
        + tier_2_years * EGYPT_TIER_2_MONTHLY_FRACTION * basic_salary
    )
    return GratuityResult(amount, "egypt_retirement", citation)
