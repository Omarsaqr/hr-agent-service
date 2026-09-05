import sqlite3
from datetime import UTC, date, datetime

import pytest

from app.api.tools.knowledge import answer_hr_question
from app.domain.models import Employee
from app.integrations.bamboohr.memory import InMemoryHRISAdapter
from app.knowledge.gaps import GapLog
from app.knowledge.store import KnowledgeStore

NOW = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)


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
            preferred_language="en",
        )
    )
    adapter.seed_employee(
        Employee(
            employee_id="emp-2",
            full_name="No Country",
            country="Atlantis",
            employment_start_date=date(2020, 1, 1),
            status="active",
            preferred_language="en",
        )
    )
    return adapter


@pytest.fixture
def knowledge_store() -> KnowledgeStore:
    return KnowledgeStore()


@pytest.fixture
def gap_log() -> GapLog:
    return GapLog(sqlite3.connect(":memory:"))


async def test_answer_hr_question_returns_a_cited_answer(
    hris: InMemoryHRISAdapter, knowledge_store: KnowledgeStore, gap_log: GapLog
) -> None:
    result = await answer_hr_question(
        "How do I get a salary certificate?", "emp-1",
        hris=hris, knowledge_store=knowledge_store, gap_log=gap_log, now=NOW,
    )

    assert result["ok"] is True
    assert result["data"]["source_doc"] == "salary_certificate"
    assert result["data"]["section"]
    assert result["message_en"]
    assert result["message_ar"]  # parallel-language rendering is populated too


async def test_answer_hr_question_no_sop_found_logs_a_gap(
    hris: InMemoryHRISAdapter, knowledge_store: KnowledgeStore, gap_log: GapLog
) -> None:
    result = await answer_hr_question(
        "Do we have a parking garage?", "emp-1",
        hris=hris, knowledge_store=knowledge_store, gap_log=gap_log, now=NOW,
    )

    assert result["ok"] is False
    assert result["code"] == "NO_SOP_FOUND"
    row = gap_log._conn.execute("SELECT question, employee_id FROM sop_gaps").fetchone()
    assert row == ("Do we have a parking garage?", "emp-1")


async def test_answer_hr_question_a_second_unrelated_question_also_logs_a_gap(
    hris: InMemoryHRISAdapter, knowledge_store: KnowledgeStore, gap_log: GapLog
) -> None:
    result = await answer_hr_question(
        "Is there a free shuttle bus?", "emp-1",
        hris=hris, knowledge_store=knowledge_store, gap_log=gap_log, now=NOW,
    )

    assert result["ok"] is False
    assert result["code"] == "NO_SOP_FOUND"


async def test_answer_hr_question_refuses_country_specific_topic_for_unsupported_country(
    hris: InMemoryHRISAdapter, knowledge_store: KnowledgeStore, gap_log: GapLog
) -> None:
    result = await answer_hr_question(
        "What is the annual leave policy?", "emp-2",
        hris=hris, knowledge_store=knowledge_store, gap_log=gap_log, now=NOW,
    )

    assert result["ok"] is False
    assert result["code"] == "COUNTRY_NOT_SUPPORTED"


async def test_answer_hr_question_unknown_employee(
    hris: InMemoryHRISAdapter, knowledge_store: KnowledgeStore, gap_log: GapLog
) -> None:
    result = await answer_hr_question(
        "How do I get a salary certificate?", "does-not-exist",
        hris=hris, knowledge_store=knowledge_store, gap_log=gap_log, now=NOW,
    )

    assert result["ok"] is False
    assert result["code"] == "EMPLOYEE_NOT_FOUND"
