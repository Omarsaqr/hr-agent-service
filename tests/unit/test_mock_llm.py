from app.integrations.llm.mock import MockLLMAdapter
from app.integrations.llm.ports import Message, ToolCall

SYSTEM_PROMPT = "you are a test assistant"


async def _generate(history: list[Message]) -> Message:
    return await MockLLMAdapter().generate(SYSTEM_PROMPT, history, tools=[])


async def test_leave_balance_question_calls_get_leave_balance() -> None:
    result = await _generate([Message(role="user", text="What's my leave balance?")])

    assert result.tool_calls[0].name == "get_leave_balance"
    assert result.tool_calls[0].arguments == {"leave_type": "annual"}


async def test_leave_request_with_dates_calls_preview() -> None:
    result = await _generate(
        [Message(role="user", text="I want to request leave from 2026-06-01 to 2026-06-05")]
    )

    call = result.tool_calls[0]
    assert call.name == "preview_leave_request"
    assert call.arguments == {
        "leave_type": "annual",
        "start_date": "2026-06-01",
        "end_date": "2026-06-05",
    }


async def test_confirm_after_a_preview_submits_using_its_token() -> None:
    history = [
        Message(role="user", text="request leave 2026-06-01 to 2026-06-05"),
        Message(
            role="assistant",
            tool_calls=[ToolCall(id="c1", name="preview_leave_request", arguments={})],
        ),
        Message(
            role="tool",
            tool_name="preview_leave_request",
            tool_call_id="c1",
            tool_result={"ok": True, "preview_token": "tok-abc", "message_en": "preview text"},
        ),
        Message(role="user", text="confirm"),
    ]

    result = await _generate(history)

    assert result.tool_calls[0].name == "submit_leave_request"
    assert result.tool_calls[0].arguments == {"preview_token": "tok-abc"}


async def test_confirm_with_nothing_pending_returns_text() -> None:
    result = await _generate([Message(role="user", text="confirm")])

    assert result.tool_calls == []
    assert "nothing pending" in (result.text or "").lower()


async def test_checkin_structured_phrase_calls_submit_daily_checkin() -> None:
    result = await _generate(
        [
            Message(
                role="user",
                text="accomplishments: shipped the report | blockers: none | rating: 4",
            )
        ]
    )

    call = result.tool_calls[0]
    assert call.name == "submit_daily_checkin"
    assert call.arguments == {
        "accomplishments": "shipped the report",
        "blockers": "none",
        "rating": 4,
    }


async def test_team_summary_question_calls_get_team_summary() -> None:
    result = await _generate([Message(role="user", text="How's my team doing this week?")])

    assert result.tool_calls[0].name == "get_team_summary"


async def test_missing_checkins_question_calls_list_missing_checkins() -> None:
    result = await _generate([Message(role="user", text="Who hasn't checked in today?")])

    assert result.tool_calls[0].name == "list_missing_checkins"


async def test_approve_phrase_calls_decide_leave_request() -> None:
    result = await _generate([Message(role="user", text="approve REQ-1 for emp-1")])

    call = result.tool_calls[0]
    assert call.name == "decide_leave_request"
    assert call.arguments == {"request_id": "REQ-1", "employee_id": "emp-1", "decision": "approved"}


async def test_pending_approvals_question_calls_list_pending_approvals() -> None:
    result = await _generate([Message(role="user", text="What requests are pending approval?")])

    assert result.tool_calls[0].name == "list_pending_approvals"


async def test_gratuity_phrase_calls_calculate_gratuity() -> None:
    # The mock matches a fixed salary-then-reason order -- a real
    # phrasing-order-agnostic parse is exactly the reasoning job left to
    # a real model; see the MockLLMAdapter docstring.
    result = await _generate(
        [Message(role="user", text="What's my gratuity? Basic salary 10000, reason resignation.")]
    )

    call = result.tool_calls[0]
    assert call.name == "calculate_gratuity"
    assert call.arguments == {"basic_salary": 10000.0, "reason": "resignation"}


async def test_unrecognized_question_falls_through_to_knowledge_base() -> None:
    result = await _generate([Message(role="user", text="How do I get a salary certificate?")])

    call = result.tool_calls[0]
    assert call.name == "answer_hr_question"
    assert call.arguments == {"question": "How do I get a salary certificate?"}


_BALANCE_RESULT = {
    "ok": True,
    "message_en": "You have 12 days.",
    "message_ar": "لديك 12 يومًا.",
}


async def test_relays_the_final_tool_result_as_text() -> None:
    history = [
        Message(role="user", text="What's my leave balance?"),
        Message(role="assistant"),
        Message(
            role="tool",
            tool_name="get_leave_balance",
            tool_call_id="c1",
            tool_result=_BALANCE_RESULT,
        ),
    ]

    result = await _generate(history)

    assert result.tool_calls == []
    assert result.text == "You have 12 days."


async def test_relays_arabic_message_for_arabic_input() -> None:
    history = [
        Message(role="user", text="كم رصيد إجازتي؟"),
        Message(role="assistant"),
        Message(
            role="tool",
            tool_name="get_leave_balance",
            tool_call_id="c1",
            tool_result=_BALANCE_RESULT,
        ),
    ]

    result = await _generate(history)

    assert result.text == "لديك 12 يومًا."


async def test_preview_result_relay_appends_a_confirm_hint() -> None:
    history = [
        Message(role="user", text="request leave 2026-06-01 to 2026-06-05"),
        Message(role="assistant"),
        Message(
            role="tool",
            tool_name="preview_leave_request",
            tool_call_id="c1",
            tool_result={"ok": True, "message_en": "Preview details.", "message_ar": "تفاصيل."},
        ),
    ]

    result = await _generate(history)

    assert "confirm" in (result.text or "").lower()
