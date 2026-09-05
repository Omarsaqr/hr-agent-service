"""Reproduces both workflows end to end with zero external credentials.

Forces every driver to its in-memory/mock default regardless of what a
developer's own .env might have configured for their own manual testing
against BambooHR/Sheets/Gemini -- this script's whole point is to work
the same way for anyone, with nothing to set up. Run with `make demo`.
"""

import asyncio
import os

# Set before importing anything under app/: Settings() is constructed at
# import time (app/main.py's module-level `app = create_app()`), and
# real process environment variables take precedence over .env, so this
# reliably overrides a developer's own driver choice rather than being
# overridden by it.
os.environ["ENVIRONMENT"] = "local"
os.environ.setdefault("PREVIEW_TOKEN_SECRET", "demo-only-secret-do-not-use-in-production")
os.environ["HRIS_DRIVER"] = "memory"
os.environ["DASHBOARD_DRIVER"] = "memory"
os.environ["LLM_DRIVER"] = "mock"
os.environ["IQAMA_SCHEDULER_ENABLED"] = "false"
# WARNING, not the app's own default: this script's output is a
# conversation transcript meant to be read, not a request log --
# per-request INFO lines (this app's own, and httpx's, since
# TestClient logs through the same root logger) would otherwise
# interleave with every printed turn.
os.environ["LOG_LEVEL"] = "WARNING"

from datetime import date  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.deps import get_hris_port  # noqa: E402
from app.domain.models import Employee  # noqa: E402
from app.integrations.bamboohr.memory import InMemoryHRISAdapter  # noqa: E402
from app.main import app  # noqa: E402

_WIDTH = 78


def _header(title: str) -> None:
    print()
    print("=" * _WIDTH)
    print(title)
    print("=" * _WIDTH)


def seed_org(client: TestClient) -> None:
    hris = get_hris_port(app.state.settings)
    # seed_employee is InMemoryHRISAdapter-only, not part of HRISPort --
    # guaranteed by forcing HRIS_DRIVER=memory above, asserted here so
    # mypy can see it too.
    assert isinstance(hris, InMemoryHRISAdapter)
    hris.seed_employee(
        Employee(
            employee_id="mgr-1",
            full_name="Fahad Al-Otaibi",
            country="KSA",
            employment_start_date=date(2016, 3, 1),
            status="active",
        )
    )
    hris.seed_employee(
        Employee(
            employee_id="emp-1",
            full_name="Sara Ahmed",
            country="KSA",
            employment_start_date=date(2021, 2, 15),
            status="active",
            manager_id="mgr-1",
        )
    )
    hris.seed_employee(
        Employee(
            employee_id="emp-2",
            full_name="Omar Khalid",
            country="UAE",
            employment_start_date=date(2019, 9, 1),
            status="active",
            manager_id="mgr-1",
        )
    )


class Conversation:
    """Prints each turn as it happens and threads session_id forward,
    so the printed transcript reads as one continuous exchange.
    """

    def __init__(self, client: TestClient) -> None:
        self._client = client
        self._session_id: str | None = None

    def say(self, actor_name: str, employee_id: str, message: str) -> str:
        response = self._client.post(
            "/chat",
            json={
                "employee_id": employee_id,
                "message": message,
                "session_id": self._session_id,
            },
        ).json()
        self._session_id = response["session_id"]
        print(f"[{actor_name}] {message}")
        print(f"[Assistant] {response['reply']}")
        print()
        return str(response["reply"])


def run_leave_workflow(client: TestClient) -> None:
    _header("Workflow: Leave Management")
    convo = Conversation(client)

    convo.say("Sara Ahmed", "emp-1", "What's my leave balance?")
    convo.say("Sara Ahmed", "emp-1", "I'd like to request leave from 2026-07-01 to 2026-07-05")
    convo.say("Sara Ahmed", "emp-1", "confirm")

    manager_convo = Conversation(client)
    manager_convo.say("Fahad Al-Otaibi", "mgr-1", "What requests are pending approval?")

    hris = get_hris_port(app.state.settings)
    pending = asyncio.run(hris.get_time_off_requests("emp-1", status="pending"))
    request_id = pending[0].request_id
    manager_convo.say("Fahad Al-Otaibi", "mgr-1", f"approve {request_id} for emp-1")


def run_checkin_workflow(client: TestClient) -> None:
    _header("Workflow: Daily Check-in and Team Performance")
    sara = Conversation(client)
    sara.say(
        "Sara Ahmed",
        "emp-1",
        "accomplishments: Shipped the Q3 report | blockers: none | rating: 5",
    )

    manager_convo = Conversation(client)
    manager_convo.say("Fahad Al-Otaibi", "mgr-1", "Who hasn't checked in today?")

    omar = Conversation(client)
    omar.say(
        "Omar Khalid",
        "emp-2",
        "accomplishments: Closed 3 support tickets | blockers: waiting on API access | rating: 4",
    )

    manager_convo.say("Fahad Al-Otaibi", "mgr-1", "How's my team doing this week?")


def run_knowledge_and_gratuity(client: TestClient) -> None:
    _header("Bonus: Knowledge Q&A and Gratuity")
    convo = Conversation(client)
    convo.say("Sara Ahmed", "emp-1", "How do I get a salary certificate?")
    convo.say("Sara Ahmed", "emp-1", "Do we have a parking garage?")
    convo.say(
        "Sara Ahmed", "emp-1", "What's my gratuity? Basic salary 12000, reason resignation."
    )


def main() -> None:
    client = TestClient(app)
    seed_org(client)

    run_leave_workflow(client)
    run_checkin_workflow(client)
    run_knowledge_and_gratuity(client)

    print()
    print("Demo complete. No external credentials were used -- HRIS_DRIVER=memory, "
          "DASHBOARD_DRIVER=memory, LLM_DRIVER=mock throughout.")


if __name__ == "__main__":
    main()
