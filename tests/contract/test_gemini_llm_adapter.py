from typing import Any

from google.genai import types

from app.integrations.llm.gemini import GeminiLLMAdapter
from app.integrations.llm.ports import Message, ToolCall, ToolSpec


class _FakeModels:
    def __init__(self, response: types.GenerateContentResponse) -> None:
        self._response = response
        self.last_call: dict[str, Any] | None = None

    async def generate_content(
        self, *, model: str, contents: list[types.Content], config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        self.last_call = {"model": model, "contents": contents, "config": config}
        return self._response


class _FakeAio:
    def __init__(self, models: _FakeModels) -> None:
        self.models = models


class _FakeClient:
    def __init__(self, response: types.GenerateContentResponse) -> None:
        self.aio = _FakeAio(_FakeModels(response))


def _text_response(text: str) -> types.GenerateContentResponse:
    content = types.Content(role="model", parts=[types.Part(text=text)])
    return types.GenerateContentResponse(candidates=[types.Candidate(content=content)])


def _function_call_response(name: str, args: dict[str, Any]) -> types.GenerateContentResponse:
    part = types.Part(function_call=types.FunctionCall(id="call-1", name=name, args=args))
    content = types.Content(role="model", parts=[part])
    return types.GenerateContentResponse(candidates=[types.Candidate(content=content)])


async def test_text_reply_produces_a_final_assistant_message() -> None:
    fake_client = _FakeClient(_text_response("You have 12 days."))
    adapter = GeminiLLMAdapter(fake_client, model="gemini-2.5-flash")  # type: ignore[arg-type]

    result = await adapter.generate(
        "system prompt", [Message(role="user", text="balance?")], tools=[]
    )

    assert result.tool_calls == []
    assert result.text == "You have 12 days."


async def test_function_call_response_becomes_a_tool_call() -> None:
    fake_client = _FakeClient(
        _function_call_response("get_leave_balance", {"leave_type": "annual"})
    )
    adapter = GeminiLLMAdapter(fake_client, model="gemini-2.5-flash")  # type: ignore[arg-type]

    result = await adapter.generate(
        "system prompt", [Message(role="user", text="balance?")], tools=[]
    )

    assert result.text is None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "get_leave_balance"
    assert result.tool_calls[0].arguments == {"leave_type": "annual"}


async def test_sends_tool_declarations_and_disables_automatic_function_calling() -> None:
    fake_client = _FakeClient(_text_response("ok"))
    adapter = GeminiLLMAdapter(fake_client, model="gemini-2.5-flash")  # type: ignore[arg-type]
    tools = [
        ToolSpec(
            name="get_leave_balance",
            description="d",
            parameters_schema={"type": "object", "properties": {}},
        )
    ]

    await adapter.generate("system prompt", [Message(role="user", text="hi")], tools=tools)

    assert fake_client.aio.models.last_call is not None
    sent_config = fake_client.aio.models.last_call["config"]
    assert sent_config.tools[0].function_declarations[0].name == "get_leave_balance"
    assert sent_config.automatic_function_calling.disable is True
    assert sent_config.system_instruction == "system prompt"


async def test_full_history_round_trip_including_a_tool_result() -> None:
    # Exercises every _to_content branch: user text, an assistant turn
    # with a tool call, and the tool-result turn sent back for it.
    fake_client = _FakeClient(_text_response("done"))
    adapter = GeminiLLMAdapter(fake_client, model="gemini-2.5-flash")  # type: ignore[arg-type]
    history = [
        Message(role="user", text="check in: shipped it"),
        Message(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="call-1",
                    name="submit_daily_checkin",
                    arguments={"accomplishments": "shipped it", "blockers": "", "rating": 4},
                )
            ],
        ),
        Message(
            role="tool",
            tool_call_id="call-1",
            tool_name="submit_daily_checkin",
            tool_result={"ok": True, "message_en": "Recorded."},
        ),
    ]

    await adapter.generate("system prompt", history, tools=[])

    assert fake_client.aio.models.last_call is not None
    sent_contents = fake_client.aio.models.last_call["contents"]
    assert [c.role for c in sent_contents] == ["user", "model", "user"]
    assert sent_contents[1].parts[0].function_call.name == "submit_daily_checkin"
    assert sent_contents[2].parts[0].function_response.name == "submit_daily_checkin"
    assert sent_contents[2].parts[0].function_response.response == {
        "ok": True,
        "message_en": "Recorded.",
    }
