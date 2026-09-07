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
# same LLMPort interface.
#
# Now exercised against a real key and a real model (gemini-3.6-flash --
# gemini-2.5-flash, the model this was first built against, was cut off
# for new users before this could be tried live): plain text and
# tool-calling both work end to end. That live run also caught a real
# gap fixtures couldn't -- see _thought_signatures below and
# docs/ROADMAP.md.
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
        # Keyed by tool-call id, populated in _extract_tool_calls. Current-
        # generation Gemini models require this exact opaque signature
        # echoed back on any later turn that replays the function call it
        # came from -- confirmed live, not discoverable from a fixture --
        # or they reject the request with 400 INVALID_ARGUMENT ("Function
        # call is missing a thought_signature"). See docs/ROADMAP.md. It
        # lives on the response Part, not on FunctionCall, so it can't
        # ride along on ToolCall itself without leaking a Gemini-specific
        # concept into the provider-agnostic type the mock adapter also
        # uses -- hence tracked here instead, as adapter-private state.
        # Process-lifetime and unbounded, same as SessionStore's own
        # history: fine at this scale, not something a long-lived
        # production process should copy unmodified.
        self._thought_signatures: dict[str, bytes] = {}

    async def generate(
        self, system_prompt: str, history: list[Message], tools: list[ToolSpec]
    ) -> Message:
        contents = [_to_content(message, self._thought_signatures) for message in history]
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

        tool_calls = self._extract_tool_calls(response)
        if tool_calls:
            return Message(role="assistant", text=None, tool_calls=tool_calls)
        return Message(role="assistant", text=response.text or "")

    def _extract_tool_calls(self, response: types.GenerateContentResponse) -> list[ToolCall]:
        # Walks the raw Parts rather than the response.function_calls
        # shortcut so each FunctionCall stays paired with its own sibling
        # thought_signature, not correlated back to it by list position.
        content = response.candidates[0].content if response.candidates else None
        parts = content.parts if content and content.parts else []

        tool_calls = []
        for part in parts:
            fc = part.function_call
            if fc is None:
                continue
            call_id = fc.id or fc.name or ""
            if part.thought_signature is not None:
                self._thought_signatures[call_id] = part.thought_signature
            tool_calls.append(ToolCall(id=call_id, name=fc.name or "", arguments=fc.args or {}))
        return tool_calls


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


def _to_content(message: Message, thought_signatures: dict[str, bytes]) -> types.Content:
    if message.role == "user":
        return types.Content(role=_USER_ROLE, parts=[types.Part(text=message.text or "")])

    if message.role == "assistant":
        if message.tool_calls:
            parts = [
                types.Part(
                    function_call=types.FunctionCall(
                        id=call.id, name=call.name, args=call.arguments
                    ),
                    thought_signature=thought_signatures.get(call.id),
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
