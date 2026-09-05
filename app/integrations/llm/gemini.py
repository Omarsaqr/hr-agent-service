from typing import Any

from google import genai
from google.genai import types

from app.integrations.llm.ports import Message, ToolCall, ToolSpec

# Built against the classic generate_content + manually-managed history
# function-calling pattern (Content/Part/role), not the newer
# Interactions API Google introduced in 2026 (client.interactions).
# Chosen deliberately: this path was directly verified by constructing
# every type used here (FunctionDeclaration, Tool, Content, Part,
# FunctionCall, FunctionResponse) against the installed SDK, while the
# Interactions API's exact request/response contract could not be
# verified without a live key. It also keeps conversation state in this
# process (SessionStore), which MockLLMAdapter needs anyway to share the
# same LLMPort interface. See docs/ROADMAP.md for what is and isn't
# verified here -- there is no live API key in this environment, so
# nothing below has been exercised against a real response.
_MODEL_ROLE = "model"
_USER_ROLE = "user"


class GeminiLLMAdapter:
    """Takes an already-constructed genai.Client, not an api_key --
    same reason BambooHRAdapter/GoogleSheetsAdapter take a client
    object rather than building their own: tests can inject a fake
    client with a matching .aio.models.generate_content shape instead
    of needing a real key or network access.
    """

    def __init__(self, client: genai.Client, model: str) -> None:
        self._client = client
        self._model = model

    async def generate(
        self, system_prompt: str, history: list[Message], tools: list[ToolSpec]
    ) -> Message:
        contents = [_to_content(message) for message in history]
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[_to_tool(tools)] if tools else None,
            # This runtime executes tools itself (they need injected
            # dependencies -- hris, dashboard, settings -- the SDK has
            # no way to provide), so automatic function calling must
            # stay off regardless of whether it would otherwise trigger.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        response = await self._client.aio.models.generate_content(
            model=self._model, contents=contents, config=config
        )

        function_calls = response.function_calls or []
        if function_calls:
            return Message(
                role="assistant",
                text=None,
                tool_calls=[
                    ToolCall(id=fc.id or fc.name or "", name=fc.name or "", arguments=fc.args or {})
                    for fc in function_calls
                ],
            )
        return Message(role="assistant", text=response.text or "")


def _to_tool(tools: list[ToolSpec]) -> types.Tool:
    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name=spec.name,
                description=spec.description,
                parameters_json_schema=spec.parameters_schema,
            )
            for spec in tools
        ]
    )


def _to_content(message: Message) -> types.Content:
    if message.role == "user":
        return types.Content(role=_USER_ROLE, parts=[types.Part(text=message.text or "")])

    if message.role == "assistant":
        if message.tool_calls:
            parts = [
                types.Part(
                    function_call=types.FunctionCall(
                        id=call.id, name=call.name, args=call.arguments
                    )
                )
                for call in message.tool_calls
            ]
            return types.Content(role=_MODEL_ROLE, parts=parts)
        return types.Content(role=_MODEL_ROLE, parts=[types.Part(text=message.text or "")])

    # role == "tool": function results are sent back as a user-role turn
    # containing function_response parts -- the documented convention
    # for this API (see the module docstring for what is/isn't verified).
    result: dict[str, Any] = message.tool_result or {}
    return types.Content(
        role=_USER_ROLE,
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=message.tool_call_id, name=message.tool_name or "", response=result
                )
            )
        ],
    )
