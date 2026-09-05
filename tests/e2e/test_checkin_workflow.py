from datetime import date

from app.domain.models import Employee
from app.integrations.bamboohr.memory import InMemoryHRISAdapter
from tests.e2e.support import E2EContext


def _seed_employee(hris: InMemoryHRISAdapter, **overrides: object) -> None:
    defaults: dict[str, object] = {
        "employee_id": "emp-1",
        "full_name": "Sara Ahmed",
        "country": "KSA",
        "employment_start_date": date(2020, 1, 1),
        "status": "active",
    }
    defaults.update(overrides)
    hris.seed_employee(Employee(**defaults))  # type: ignore[arg-type]


async def test_checkin_then_manager_sees_it_in_the_team_summary(e2e: E2EContext) -> None:
    _seed_employee(e2e.hris, employee_id="mgr-1", full_name="Manager One", manager_id=None)
    _seed_employee(e2e.hris, employee_id="emp-1", full_name="Sara Ahmed", manager_id="mgr-1")
    _seed_employee(e2e.hris, employee_id="emp-2", full_name="Omar Khalid", manager_id="mgr-1")

    checkin = e2e.client.post(
        "/chat",
        json={
            "employee_id": "emp-1",
            "message": "accomplishments: shipped the report | blockers: none | rating: 4",
        },
    ).json()
    assert checkin["reply"]

    stored = await e2e.dashboard.get_checkins(["emp-1"], date.today(), date.today())
    assert len(stored) == 1
    assert stored[0].rating == 4

    # Only emp-1 checked in -- emp-2 should show up as missing from both
    # angles a manager might ask about the same underlying gap.
    missing = e2e.client.post(
        "/chat", json={"employee_id": "mgr-1", "message": "Who hasn't checked in today?"}
    ).json()
    assert "Omar Khalid" in missing["reply"]
    assert "Sara Ahmed" not in missing["reply"]

    summary = e2e.client.post(
        "/chat", json={"employee_id": "mgr-1", "message": "How's my team doing this week?"}
    ).json()
    assert "1" in summary["reply"]  # 1 of 2 checked in
    assert "4.0" in summary["reply"] or "4" in summary["reply"]  # average rating

    # emp-2 checks in too -- the gap should close.
    e2e.client.post(
        "/chat",
        json={
            "employee_id": "emp-2",
            "message": "accomplishments: fixed the bug | blockers: none | rating: 5",
        },
    )

    missing_again = e2e.client.post(
        "/chat", json={"employee_id": "mgr-1", "message": "Who hasn't checked in today?"}
    ).json()
    assert "everyone" in missing_again["reply"].lower()


async def test_checkin_replay_with_the_same_wording_does_not_double_count(
    e2e: E2EContext,
) -> None:
    # The mock's tool-call id is fresh per invocation, so two separate
    # messages produce two separate idempotency keys -- this is
    # deliberately two distinct submissions on the same day, and the
    # dashboard's own "latest wins" rule (not idempotency) is what keeps
    # get_checkins from double-counting same-day resubmissions.
    _seed_employee(e2e.hris, employee_id="emp-1", full_name="Sara Ahmed")

    first = e2e.client.post(
        "/chat",
        json={
            "employee_id": "emp-1",
            "message": "accomplishments: draft one | blockers: none | rating: 3",
        },
    ).json()
    second = e2e.client.post(
        "/chat",
        json={
            "employee_id": "emp-1",
            "message": "accomplishments: final version | blockers: none | rating: 5",
        },
    ).json()

    assert first["reply"]
    assert second["reply"]
    stored = await e2e.dashboard.get_checkins(["emp-1"], date.today(), date.today())
    assert len(stored) == 1
    assert stored[0].accomplishments == "final version"
    assert stored[0].rating == 5
