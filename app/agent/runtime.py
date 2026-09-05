import logging
from datetime import date, datetime

from app.agent.tools import TOOLS_BY_NAME, ChatDeps, ToolContext
from app.integrations.llm.ports import LLMPort, Message

logger = logging.getLogger("app.agent")

# A confirm-then-submit leave request is at most 2 tool calls; nothing
# else here chains more than one. This exists to stop a misbehaving
# model from looping forever, not to accommodate a legitimately long
# chain.
MAX_TOOL_ITERATIONS = 6

SYSTEM_PROMPT = """You are the HR assistant for a multi-country industrial company operating in \
Saudi Arabia, UAE, Egypt, and Jordan. You help with two things: leave management (checking \
balances, requesting and approving leave) and daily check-ins / team performance -- plus general \
HR policy questions.

Rules:
1. Never compute or state a number yourself -- leave balances, working days, gratuity amounts, \
dates. Always come from a tool result. If you don't have a tool result with the number, say you \
don't know rather than estimate.
2. For leave requests: always call preview_leave_request first and show the user the preview \
(working days, balance impact, approver) before calling submit_leave_request. Only call \
submit_leave_request after the user has explicitly confirmed the preview in their own message -- \
never submit on the same turn as the first preview.
3. If a tool result has ok: false, relay its message and recovery_hint honestly. Don't apologize \
elaborately or invent a workaround -- tell the user what to do next using the recovery_hint.
4. Respond in the same language the user wrote in. Tool results include both message_en and \
message_ar -- use whichever matches the user's language, or compose your own response from the \
result's data in that language, but never invent numbers that aren't in the data.
5. You are already talking to one specific, authenticated employee. Tools that act on "the \
current user" (get_leave_balance, preview_leave_request, submit_daily_checkin, and so on) never \
take an employee id parameter for that user -- you don't need to ask for or guess one.
6. Be concise. This is a chat interface, not an essay."""


async def run_chat_turn(
    user_text: str,
    history: list[Message],
    *,
    llm: LLMPort,
    deps: ChatDeps,
    acting_employee_id: str,
    now: datetime,
    as_of: date,
) -> str:
    """Runs one user turn to completion: appends the user message,
    drives the generate -> execute-tools -> generate loop until the
    model produces final text (or the iteration cap is hit), and
    returns that text. history is mutated in place -- the caller (the
    session store) owns its lifetime.
    """
    history.append(Message(role="user", text=user_text))
    tool_specs = [tool.spec for tool in TOOLS_BY_NAME.values()]

    for _ in range(MAX_TOOL_ITERATIONS):
        assistant_message = await llm.generate(SYSTEM_PROMPT, history, tool_specs)
        history.append(assistant_message)

        if not assistant_message.tool_calls:
            return assistant_message.text or ""

        for call in assistant_message.tool_calls:
            agent_tool = TOOLS_BY_NAME.get(call.name)
            if agent_tool is None:
                result = {
                    "ok": False,
                    "code": "UNKNOWN_TOOL",
                    "message_en": f"No such tool: {call.name}",
                    "message_ar": f"لا توجد أداة بهذا الاسم: {call.name}",
                }
            else:
                ctx = ToolContext(
                    deps=deps,
                    acting_employee_id=acting_employee_id,
                    call_id=call.id,
                    now=now,
                    as_of=as_of,
                )
                try:
                    result = await agent_tool.handler(call.arguments, ctx)
                except Exception:
                    logger.exception("tool %s raised during a chat turn", call.name)
                    result = {
                        "ok": False,
                        "code": "TOOL_ERROR",
                        "message_en": "Something went wrong running that action.",
                        "message_ar": "حدث خطأ أثناء تنفيذ هذا الإجراء.",
                    }
            history.append(
                Message(role="tool", tool_call_id=call.id, tool_name=call.name, tool_result=result)
            )

    return (
        "I'm having trouble completing this request right now -- please try again, or contact "
        "HR directly."
    )
