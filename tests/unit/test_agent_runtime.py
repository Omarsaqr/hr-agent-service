import sqlite3
from datetime import UTC, date, datetime

import pytest

from app.agent.runtime import run_chat_turn
from app.agent.tools import ChatDeps
from app.config import Settings
from app.core.audit import AuditLog
from app.core.idempotency import IdempotencyStore, NonceStore
from app.domain.models import Employee
from app.integrations.bamboohr.memory import InMemoryHRISAdapter
from app.integrations.llm.mock import MockLLMAdapter
from app.integrations.llm.ports import Message, ToolCall
from app.integrations.sheets.memory import InMemorySheetAdapter
from app.knowledge.gaps import GapLog
from app.knowledge.store import KnowledgeStore

AS_OF = date(2026, 6, 1)
NOW = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)


def make_settings() -> Settings:
    return Settings(_env_file=None, environment="test", preview_token_secret="test-secret")


@pytest.fixture
def hris() -> InMemoryHRISAdapter:
    adapter = InMemoryHRISAdapter()
    adapter.seed_employee(
        Employee(
            employee_id="emp-1",
            full_name="Sara Ahmed",
            country="KSA",
            employment_start_date=date(2020, 1, 1),
            status="active",
            manager_id="mgr-1",
        )
    )
    adapter.seed_employee(
        Employee(
            employee_id="mgr-1",
            full_name="Manager One",
            country="KSA",
            employment_start_date=date(2015, 1, 1),
            status="active",
        )
    )
    return adapter


@pytest.fixture
def deps(hris: InMemoryHRISAdapter) -> ChatDeps:
    return ChatDeps(
        hris=hris,
        dashboard=InMemorySheetAdapter(),
        settings=make_settings(),
        nonce_store=NonceStore(sqlite3.connect(":memory:")),
        idempotency_store=IdempotencyStore(sqlite3.connect(":memory:")),
        audit_log=AuditLog(sqlite3.connect(":memory:")),
        knowledge_store=KnowledgeStore(),
        gap_log=GapLog(sqlite3.connect(":memory:")),
    )


async def test_a_simple_question_resolves_in_one_turn(deps: ChatDeps) -> None:
    history: list[Message] = []

    reply = await run_chat_turn(
        "What's my leave balance?",
        history,
        llm=MockLLMAdapter(),
        deps=deps,
        acting_employee_id="emp-1",
        now=NOW,
        as_of=AS_OF,
    )

    assert "day" in reply.lower()
    # user, assistant(tool_call), tool(result), assistant(final text)
    assert len(history) == 4
    assert history[-1].role == "assistant"


async def test_leave_request_preview_then_confirm_across_two_turns(deps: ChatDeps) -> None:
    history: list[Message] = []
    llm = MockLLMAdapter()

    preview_reply = await run_chat_turn(
        "request leave 2026-06-10 to 2026-06-12",
        history,
        llm=llm,
        deps=deps,
        acting_employee_id="emp-1",
        now=NOW,
        as_of=AS_OF,
    )
    assert "confirm" in preview_reply.lower()

    submit_reply = await run_chat_turn(
        "confirm", history, llm=llm, deps=deps, acting_employee_id="emp-1", now=NOW, as_of=AS_OF
    )

    assert "submitted" in submit_reply.lower()
    stored = await deps.hris.get_time_off_requests("emp-1")
    assert len(stored) == 1


async def test_unknown_tool_name_produces_a_structured_error_not_a_crash(deps: ChatDeps) -> None:
    class BrokenLLM:
        async def generate(self, system_prompt, history, tools):  # type: ignore[no-untyped-def]
            if history and history[-1].role == "tool":
                return Message(role="assistant", text=history[-1].tool_result["message_en"])
            return Message(
                role="assistant",
                tool_calls=[ToolCall(id="c1", name="not_a_real_tool", arguments={})],
            )

    history: list[Message] = []
    reply = await run_chat_turn(
        "do the thing", history, llm=BrokenLLM(), deps=deps,
        acting_employee_id="emp-1", now=NOW, as_of=AS_OF,
    )

    assert "no such tool" in reply.lower()


async def test_a_tool_that_raises_is_caught_and_reported_not_propagated(deps: ChatDeps) -> None:
    class ExplodingLLM:
        async def generate(self, system_prompt, history, tools):  # type: ignore[no-untyped-def]
            if history and history[-1].role == "tool":
                return Message(role="assistant", text=history[-1].tool_result["message_en"])
            return Message(
                role="assistant",
                # Missing required "leave_type" -> the real handler raises a KeyError.
                tool_calls=[ToolCall(id="c1", name="get_leave_balance", arguments={})],
            )

    history: list[Message] = []
    reply = await run_chat_turn(
        "balance please", history, llm=ExplodingLLM(), deps=deps,
        acting_employee_id="emp-1", now=NOW, as_of=AS_OF,
    )

    assert "went wrong" in reply.lower()
