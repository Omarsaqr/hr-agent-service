from datetime import UTC, date, datetime

from app.core.company_time import today_in_company_timezone
from app.domain.models import Employee
from app.integrations.bamboohr.memory import InMemoryHRISAdapter
from tests.e2e.support import E2EContext


def _seed_employee(hris: InMemoryHRISAdapter, **overrides: object) -> None:
    defaults: dict[str, object] = {
        "employee_id": "emp-1",
        "full_name": "Sara Ahmed",
        "country": "KSA",
        "employment_start_date": date(2015, 1, 1),
        "status": "active",
    }
    defaults.update(overrides)
    hris.seed_employee(Employee(**defaults))  # type: ignore[arg-type]


async def test_hr_policy_question_gets_a_cited_answer(e2e: E2EContext) -> None:
    _seed_employee(e2e.hris)

    result = e2e.client.post(
        "/chat", json={"employee_id": "emp-1", "message": "How do I get a salary certificate?"}
    ).json()

    assert "salary certificate" in result["reply"].lower()


async def test_a_question_with_no_matching_sop_is_logged_as_a_gap(e2e: E2EContext) -> None:
    _seed_employee(e2e.hris)

    result = e2e.client.post(
        "/chat", json={"employee_id": "emp-1", "message": "Do we have a parking garage?"}
    ).json()

    assert "logged" in result["reply"].lower()


async def test_gratuity_question_returns_a_computed_estimate(e2e: E2EContext) -> None:
    # Hire date relative to *today* (same month/day, 10 years back), not
    # a fixed date: years_of_service depends on completed_months_of_
    # service(hire_date, as_of=today), so a fixed hire date would give a
    # different fractional-year answer depending on which real day this
    # test happens to run on -- same month/day guarantees exactly 10.0
    # years regardless of when that is. today_in_company_timezone, not
    # date.today(): the server computes as_of the same way (chat.py), and
    # the two disagree for part of every real day on a UTC-timezone test
    # runner -- exactly the bug this test file already exists to catch
    # (see test_checkin_workflow.py's own history of the same mistake).
    today = today_in_company_timezone(datetime.now(UTC))
    try:
        ten_years_ago = today.replace(year=today.year - 10)
    except ValueError:
        ten_years_ago = today.replace(year=today.year - 10, day=28)  # today was Feb 29
    _seed_employee(e2e.hris, employment_start_date=ten_years_ago)
    # KSA, termination (full award, no resignation scaling):
    # 5 years * 0.5 + 5 years * 1.0 = 7.5 months' salary at 10,000/month.

    result = e2e.client.post(
        "/chat",
        json={
            "employee_id": "emp-1",
            "message": "What's my gratuity? Basic salary 10000, reason termination.",
        },
    ).json()

    assert "75,000" in result["reply"] or "75000" in result["reply"]
