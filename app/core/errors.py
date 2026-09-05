from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolError(Exception):
    """Structured failure a tool returns to the agent -- never a bare 500
    or a stack trace. recovery_hint is written for the model to act on,
    not for a human to read in a log.
    """

    code: str
    message_en: str
    message_ar: str
    recovery_hint: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_response(self) -> dict[str, Any]:
        return {
            "ok": False,
            "code": self.code,
            "message_en": self.message_en,
            "message_ar": self.message_ar,
            "recovery_hint": self.recovery_hint,
            "data": self.data,
        }


def employee_not_found() -> dict[str, Any]:
    """Shared across every tool that takes an employee_id: leave, knowledge,
    and check-in tools all hit the same failure the same way."""
    return ToolError(
        code="EMPLOYEE_NOT_FOUND",
        message_en="I couldn't find an employee record for that id.",
        message_ar="لم أتمكن من العثور على سجل موظف بهذا المعرف.",
        recovery_hint="Confirm the employee id came from resolve_employee, not user input.",
    ).to_response()
