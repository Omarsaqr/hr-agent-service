from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

Role = Literal["user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Message:
    """Provider-agnostic conversation turn. GeminiLLMAdapter translates a
    list of these into google.genai's Content/Part shape on every call;
    no vendor type crosses this boundary, the same rule D1 applies to
    HRIS/Dashboard adapters.
    """

    role: Role
    text: str | None = None
    # Set only on an assistant message that calls tools.
    tool_calls: list[ToolCall] = field(default_factory=list)
    # Set only on a tool-role message (the result of one tool_calls entry).
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_result: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters_schema: dict[str, Any]


@runtime_checkable
class LLMPort(Protocol):
    async def generate(
        self, system_prompt: str, history: list[Message], tools: list[ToolSpec]
    ) -> Message:
        """The next assistant turn: either final text (tool_calls empty)
        or one or more tool calls for the caller to execute and append
        back as tool-role Messages before calling generate() again.
        """
        ...
