from datetime import date

from app.domain.countries import AnnualLeavePolicy, EntitlementTier


def completed_months_of_service(reference: date, as_of: date) -> int:
    months = (as_of.year - reference.year) * 12 + (as_of.month - reference.month)
    if as_of.day < reference.day:
        # Anniversary day hasn't been reached yet this month -- the current
        # month doesn't count as complete. This is what keeps tenure from
        # jumping a full year early for anyone whose hire date falls late
        # in the calendar year relative to `as_of`.
        months -= 1
    return max(months, 0)


def age_in_years(birth_date: date, as_of: date) -> int:
    return completed_months_of_service(birth_date, as_of) // 12


def _tier_qualifies(tier: EntitlementTier, completed_months: int, age: int | None) -> bool:
    if completed_months >= tier.min_months:
        return True
    return (
        tier.min_age_alternative is not None
        and age is not None
        and age >= tier.min_age_alternative
    )


def annual_leave_entitlement(
    policy: AnnualLeavePolicy, completed_months: int, age: int | None = None
) -> float:
    applicable: EntitlementTier | None = None
    for tier in policy.tiers:
        # Tiers are sorted ascending by min_months; the last one that
        # qualifies is the current one, whether reached by tenure or age.
        if _tier_qualifies(tier, completed_months, age):
            applicable = tier

    if applicable is None:
        return 0.0
    if applicable.annual_days is not None:
        return applicable.annual_days

    accrual_months = max(completed_months - applicable.min_months, 0)
    return accrual_months * (applicable.monthly_accrual_days or 0.0)
