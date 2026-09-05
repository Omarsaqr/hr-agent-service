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


async def test_balance_then_preview_then_confirm_then_manager_approves(
    e2e: E2EContext,
) -> None:
    _seed_employee(e2e.hris, employee_id="emp-1", full_name="Sara Ahmed", manager_id="mgr-1")
    _seed_employee(e2e.hris, employee_id="mgr-1", full_name="Manager One", manager_id=None)

    # 1. Employee checks their balance.
    balance = e2e.client.post(
        "/chat", json={"employee_id": "emp-1", "message": "What's my leave balance?"}
    ).json()
    assert "day" in balance["reply"].lower()

    # 2. Employee previews a leave request -- same session, so the
    # eventual "confirm" can find this preview's token in history.
    preview = e2e.client.post(
        "/chat",
        json={
            "employee_id": "emp-1",
            "message": "request leave 2026-06-10 to 2026-06-12",
            "session_id": balance["session_id"],
        },
    ).json()
    assert "confirm" in preview["reply"].lower()
    # Nothing committed yet -- a preview must never write anything.
    assert await e2e.hris.get_time_off_requests("emp-1") == []

    # 3. Employee confirms -- this is the actual write.
    submit = e2e.client.post(
        "/chat",
        json={"employee_id": "emp-1", "message": "confirm", "session_id": preview["session_id"]},
    ).json()
    assert "submitted" in submit["reply"].lower()

    stored = await e2e.hris.get_time_off_requests("emp-1")
    assert len(stored) == 1
    assert stored[0].status == "pending"
    request_id = stored[0].request_id

    # 4. Manager sees it as a pending approval.
    pending = e2e.client.post(
        "/chat", json={"employee_id": "mgr-1", "message": "What requests are pending approval?"}
    ).json()
    assert "1" in pending["reply"]

    # 5. Manager approves it by id.
    decision = e2e.client.post(
        "/chat",
        json={"employee_id": "mgr-1", "message": f"approve {request_id} for emp-1"},
    ).json()
    assert "approved" in decision["reply"].lower()

    updated = await e2e.hris.get_time_off_requests("emp-1")
    assert updated[0].status == "approved"
    assert updated[0].decided_by == "mgr-1"


async def test_a_second_employees_manager_cannot_approve_someone_elses_request(
    e2e: E2EContext,
) -> None:
    _seed_employee(e2e.hris, employee_id="emp-1", full_name="Sara Ahmed", manager_id="mgr-1")
    _seed_employee(e2e.hris, employee_id="mgr-1", full_name="Manager One", manager_id=None)
    _seed_employee(e2e.hris, employee_id="mgr-2", full_name="Manager Two", manager_id=None)

    preview = e2e.client.post(
        "/chat",
        json={"employee_id": "emp-1", "message": "request leave 2026-06-10 to 2026-06-12"},
    ).json()
    submit = e2e.client.post(
        "/chat",
        json={"employee_id": "emp-1", "message": "confirm", "session_id": preview["session_id"]},
    ).json()
    assert "submitted" in submit["reply"].lower()
    request_id = (await e2e.hris.get_time_off_requests("emp-1"))[0].request_id

    # mgr-2 is not emp-1's manager -- decide_leave_request re-derives the
    # authorized approver server-side and must refuse this regardless of
    # what the chat message claims.
    decision = e2e.client.post(
        "/chat",
        json={"employee_id": "mgr-2", "message": f"approve {request_id} for emp-1"},
    ).json()

    assert "authoris" in decision["reply"].lower()
    still_pending = await e2e.hris.get_time_off_requests("emp-1")
    assert still_pending[0].status == "pending"


async def test_leave_request_conversation_in_arabic_replies_in_arabic(e2e: E2EContext) -> None:
    _seed_employee(e2e.hris, employee_id="emp-1", full_name="Sara Ahmed")

    result = e2e.client.post(
        "/chat", json={"employee_id": "emp-1", "message": "كم رصيد إجازتي؟"}
    ).json()

    # Mixed Arabic/Latin is expected (day counts, ISO dates); the sentence
    # itself must be Arabic, checked via the same script range the
    # server and the web portal both use.
    assert any("؀" <= ch <= "ۿ" for ch in result["reply"])
