import re
from typing import Any

from app.core.i18n import detect_script, resolve_language
from app.integrations.llm.ports import Message, ToolCall, ToolSpec

_LEAVE_BALANCE_RE = re.compile(r"\bleave balance\b|\bbalance\b", re.IGNORECASE)
_LEAVE_REQUEST_RE = re.compile(
    r"\b(request|take)\b.*?\bleave\b.*?(\d{4}-\d{2}-\d{2}).*?(?:to|until|-)\s*(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE | re.DOTALL,
)
_CONFIRM_RE = re.compile(r"^\s*(yes|confirm|go ahead|do it|submit it)\b", re.IGNORECASE)
_CHECKIN_RE = re.compile(
    r"accomplishments\s*:\s*(?P<accomplishments>.*?)\s*\|\s*blockers\s*:\s*(?P<blockers>.*?)"
    r"\s*\|\s*rating\s*:\s*(?P<rating>\d)",
    re.IGNORECASE | re.DOTALL,
)
_TEAM_SUMMARY_RE = re.compile(r"\bteam summary\b|how('?s| is) my team", re.IGNORECASE)
_MISSING_CHECKIN_RE = re.compile(
    r"missing check.?in|who hasn'?t checked in|haven'?t checked in", re.IGNORECASE
)
_PENDING_APPROVALS_RE = re.compile(
    r"pending approvals?|requests? (waiting|to approve)", re.IGNORECASE
)
_DECIDE_RE = re.compile(
    r"\b(?P<decision>approve|reject)\b\s+(?P<request_id>\S+)\s+for\s+(?P<employee_id>\S+)",
    re.IGNORECASE,
)
_GRATUITY_RE = re.compile(
    r"gratuity.*?salary\D*(?P<salary>\d+(?:\.\d+)?).*?"
    r"(?P<reason>termination for cause|death or disability|resignation|termination"
    r"|retirement|death|disability)",
    re.IGNORECASE | re.DOTALL,
)
_REASON_ALIASES = {"death": "death_or_disability", "disability": "death_or_disability"}


class MockLLMAdapter:
    """Deterministic, credential-free stand-in for a real LLM.

    This is the default driver -- what scripts/seed_demo.py and the
    end-to-end tests run against, so both workflows are demonstrable
    with zero external credentials, the same "memory by default" shape
    as HRIS_DRIVER/DASHBOARD_DRIVER. It recognizes simple keyword and
    structured patterns, not free-form natural language -- turning
    English/Arabic prose into tool calls is exactly the reasoning job a
    real model does; a rule-based stand-in doing that job convincingly
    would be pretending to be smarter than it is. GeminiLLMAdapter is
    what handles actual conversational phrasing. See docs/ROADMAP.md.
    """

    async def generate(
        self, system_prompt: str, history: list[Message], tools: list[ToolSpec]
    ) -> Message:
        if history and history[-1].role == "tool":
            return _relay_tool_result(history[-1], history)

        last_user = _last_user_text(history)
        if last_user is None:
            return Message(role="assistant", text="I didn't catch that -- could you rephrase?")

        if _CONFIRM_RE.match(last_user.strip()):
            token = _find_latest_preview_token(history)
            if token is None:
                return Message(role="assistant", text="There's nothing pending to confirm.")
            return _call("submit_leave_request", {"preview_token": token})

        leave_request_match = _LEAVE_REQUEST_RE.search(last_user)
        if leave_request_match:
            return _call(
                "preview_leave_request",
                {
                    "leave_type": "annual",
                    "start_date": leave_request_match.group(2),
                    "end_date": leave_request_match.group(3),
                },
            )

        if _LEAVE_BALANCE_RE.search(last_user):
            return _call("get_leave_balance", {"leave_type": "annual"})

        checkin_match = _CHECKIN_RE.search(last_user)
        if checkin_match:
            return _call(
                "submit_daily_checkin",
                {
                    "accomplishments": checkin_match["accomplishments"].strip(),
                    "blockers": checkin_match["blockers"].strip(),
                    "rating": int(checkin_match["rating"]),
                },
            )

        if _TEAM_SUMMARY_RE.search(last_user):
            return _call("get_team_summary", {})

        if _MISSING_CHECKIN_RE.search(last_user):
            return _call("list_missing_checkins", {})

        decide_match = _DECIDE_RE.search(last_user)
        if decide_match:
            decision = "approved" if decide_match["decision"].lower() == "approve" else "rejected"
            return _call(
                "decide_leave_request",
                {
                    "request_id": decide_match["request_id"],
                    "employee_id": decide_match["employee_id"],
                    "decision": decision,
                },
            )

        if _PENDING_APPROVALS_RE.search(last_user):
            return _call("list_pending_approvals", {})

        gratuity_match = _GRATUITY_RE.search(last_user)
        if gratuity_match:
            reason = gratuity_match["reason"].lower().replace(" ", "_")
            reason = _REASON_ALIASES.get(reason, reason)
            return _call(
                "calculate_gratuity",
                {"basic_salary": float(gratuity_match["salary"]), "reason": reason},
            )

        # Falls through to the knowledge base for anything unrecognized --
        # a real model would decide this; the mock's default is "assume
        # it's a policy question" rather than refusing outright.
        return _call("answer_hr_question", {"question": last_user})


def _call(name: str, arguments: dict[str, Any]) -> Message:
    call = ToolCall(id=f"mock-{name}", name=name, arguments=arguments)
    return Message(role="assistant", text=None, tool_calls=[call])


def _last_user_text(history: list[Message]) -> str | None:
    for message in reversed(history):
        if message.role == "user":
            return message.text
    return None


def _find_latest_preview_token(history: list[Message]) -> str | None:
    for message in reversed(history):
        if message.role == "tool" and message.tool_name == "preview_leave_request":
            result = message.tool_result or {}
            token = result.get("preview_token")
            return token if isinstance(token, str) else None
    return None


def _relay_tool_result(tool_message: Message, history: list[Message]) -> Message:
    result = tool_message.tool_result or {}
    user_text = _last_user_text(history) or ""
    language = resolve_language(None, detect_script(user_text))
    text = result.get(f"message_{language}") or result.get("message_en") or ""

    if tool_message.tool_name == "preview_leave_request" and result.get("ok"):
        hint = (
            " Reply 'confirm' to submit this request."
            if language == "en"
            else " أرسل 'confirm' لتقديم هذا الطلب."
        )
        text = f"{text}{hint}"

    return Message(role="assistant", text=text)
