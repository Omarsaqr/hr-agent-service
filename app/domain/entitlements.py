from datetime import date, timedelta

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


def years_of_service(employment_start_date: date, as_of: date) -> float:
    # Whole completed months, same granularity tenure is tracked at
    # everywhere else in this system (leave entitlement, sick leave
    # tiers) -- gratuity doesn't get its own day-level precision just
    # because it's a monetary figure.
    return completed_months_of_service(employment_start_date, as_of) / 12.0


def current_leave_year_bounds(employment_start_date: date, as_of: date) -> tuple[date, date]:
    """The (start, end) of the leave year containing `as_of` -- the most
    recent hire-date anniversary on or before `as_of`, through the day
    before the next one.

    Entitlement accrues per year of service from the hire date, not the
    calendar year, so "days taken" must be scoped the same way on *both*
    ends -- taken days from a previous or future service year shouldn't
    affect this year's balance. This end bound is load-bearing, not
    decorative: `HRISPort.get_time_off_taken`'s `until` parameter must be
    computed from this function, not a separate inline calculation, or
    the two can silently drift out of sync the way `since` alone once did
    (an approved request dated in a later leave year was being counted
    against the current one -- see docs/ROADMAP.md).
    """

    def anniversary_in(year: int) -> date:
        try:
            return employment_start_date.replace(year=year)
        except ValueError:
            # employment_start_date was Feb 29; `year` isn't a leap year.
            return employment_start_date.replace(year=year, day=28)

    this_year = anniversary_in(as_of.year)
    start = this_year if this_year <= as_of else anniversary_in(as_of.year - 1)
    end = anniversary_in(start.year + 1) - timedelta(days=1)
    return start, end


def _tier_qualifies(
    tier: EntitlementTier, completed_months: int, age: int | None, prior_threshold: int
) -> bool:
    if completed_months >= tier.min_months:
        return True
    # An age alternative substitutes for *this* tier's own min_months --
    # it doesn't also waive the tiers below it. Someone newly hired at 52
    # hasn't "had service" yet, so they still land on the entry tier
    # instead of vaulting past the ones a same-tenure younger hire would
    # have to clear first.
    return (
        tier.min_age_alternative is not None
        and age is not None
        and age >= tier.min_age_alternative
        and completed_months >= prior_threshold
    )


def annual_leave_entitlement(
    policy: AnnualLeavePolicy, completed_months: int, age: int | None = None
) -> float:
    applicable: EntitlementTier | None = None
    prior_threshold = 0
    for tier in policy.tiers:
        # Tiers are sorted ascending by min_months; the last one that
        # qualifies is the current one, whether reached by tenure or age.
        if _tier_qualifies(tier, completed_months, age, prior_threshold):
            applicable = tier
        prior_threshold = tier.min_months

    if applicable is None:
        return 0.0
    if applicable.annual_days is not None:
        return applicable.annual_days

    accrual_months = max(completed_months - applicable.min_months, 0)
    return accrual_months * (applicable.monthly_accrual_days or 0.0)


def annual_leave_balance(entitlement_days: float, taken_days: float) -> float:
    # Not clamped to zero: an employee can legitimately be over-drawn
    # (e.g. a mid-year policy or tenure-tier change), and a negative
    # result surfaces that honestly instead of hiding it as zero.
    return entitlement_days - taken_days
