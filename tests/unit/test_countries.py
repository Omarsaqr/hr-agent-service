from datetime import date

from app.domain.countries import COUNTRY_POLICIES


def test_all_four_countries_are_loaded() -> None:
    assert set(COUNTRY_POLICIES) == {"KSA", "UAE", "Egypt", "Jordan"}


def test_every_annual_leave_policy_carries_citation_and_source() -> None:
    for code, policy in COUNTRY_POLICIES.items():
        annual = policy.annual_leave
        assert annual.citation, code
        assert annual.source_url.startswith("http"), code
        assert isinstance(annual.last_reviewed, date), code


def test_annual_leave_tiers_are_sorted_ascending_by_min_months() -> None:
    for code, policy in COUNTRY_POLICIES.items():
        months = [tier.min_months for tier in policy.annual_leave.tiers]
        assert months == sorted(months), code


def test_only_ksa_has_a_sick_leave_policy() -> None:
    assert COUNTRY_POLICIES["KSA"].sick_leave is not None
    assert COUNTRY_POLICIES["UAE"].sick_leave is None
    assert COUNTRY_POLICIES["Egypt"].sick_leave is None
    assert COUNTRY_POLICIES["Jordan"].sick_leave is None


def test_ksa_sick_leave_tiers_sum_to_120_days_at_the_documented_percentages() -> None:
    sick_leave = COUNTRY_POLICIES["KSA"].sick_leave
    assert sick_leave is not None
    tiers = sick_leave.tiers

    assert [(t.max_cumulative_days, t.pay_percentage) for t in tiers] == [
        (30, 100),
        (90, 75),
        (120, 0),
    ]


def test_egypt_annual_leave_carries_a_note_on_the_law_change() -> None:
    note = COUNTRY_POLICIES["Egypt"].annual_leave.note

    assert note is not None
    assert "14 of 2025" in note
