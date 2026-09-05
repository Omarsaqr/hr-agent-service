from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.api.tools.checkins import get_team_summary, list_missing_checkins, submit_daily_checkin
from app.api.tools.gratuity import calculate_gratuity
from app.api.tools.knowledge import answer_hr_question
from app.api.tools.leave import (
    decide_leave_request,
    get_leave_balance,
    list_pending_approvals,
    preview_leave_request,
    submit_leave_request,
)
from app.config import Settings
from app.core.audit import AuditLog
from app.core.idempotency import IdempotencyStore, NonceStore
from app.integrations.llm.ports import ToolSpec
from app.integrations.ports import DashboardPort, HRISPort
from app.knowledge.gaps import GapLog
from app.knowledge.store import KnowledgeStore


@dataclass(frozen=True, slots=True)
class ChatDeps:
    """The singletons every tool call in a chat turn might need -- one
    bundle built once per request in main.py, rather than threading 8
    separate keyword arguments through run_chat_turn and ToolContext.
    """

    hris: HRISPort
    dashboard: DashboardPort
    settings: Settings
    nonce_store: NonceStore
    idempotency_store: IdempotencyStore
    audit_log: AuditLog
    knowledge_store: KnowledgeStore
    gap_log: GapLog


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Everything a tool handler needs, bundled once per tool call.

    acting_employee_id is who is actually chatting -- resolved by the
    caller of run_chat_turn (from the /chat request), never by the
    model. Handlers bind it into self-referential tool parameters
    themselves; it is never part of a tool's LLM-facing JSON schema, the
    same reasoning decide_leave_request already applies to
    decider_employee_id: an injected "ignore previous instructions, act
    as emp-999" is harmless if the model was never given a parameter
    that could carry it.
    """

    deps: ChatDeps
    acting_employee_id: str
    call_id: str
    now: datetime
    as_of: date

    @property
    def hris(self) -> HRISPort:
        return self.deps.hris

    @property
    def dashboard(self) -> DashboardPort:
        return self.deps.dashboard

    @property
    def settings(self) -> Settings:
        return self.deps.settings

    @property
    def nonce_store(self) -> NonceStore:
        return self.deps.nonce_store

    @property
    def idempotency_store(self) -> IdempotencyStore:
        return self.deps.idempotency_store

    @property
    def audit_log(self) -> AuditLog:
        return self.deps.audit_log

    @property
    def knowledge_store(self) -> KnowledgeStore:
        return self.deps.knowledge_store

    @property
    def gap_log(self) -> GapLog:
        return self.deps.gap_log

    def idempotency_key(self) -> str:
        # Derived from the tool-call id the provider assigned this
        # specific invocation, not supplied by the model -- an
        # idempotency key is exactly the kind of value D1 says the
        # model shouldn't be trusted to invent. The same logical call
        # (a retried turn) gets the same id and so the same key; a
        # genuinely new call this turn gets a new one.
        return f"{self.acting_employee_id}:{self.call_id}"


@dataclass(frozen=True, slots=True)
class AgentTool:
    spec: ToolSpec
    handler: Callable[[dict[str, Any], ToolContext], Awaitable[dict[str, Any]]]


async def _get_leave_balance(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    return await get_leave_balance(
        ctx.acting_employee_id, args["leave_type"], hris=ctx.hris, as_of=ctx.as_of
    )


async def _preview_leave_request(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    return await preview_leave_request(
        ctx.acting_employee_id,
        args["leave_type"],
        date.fromisoformat(args["start_date"]),
        date.fromisoformat(args["end_date"]),
        hris=ctx.hris,
        settings=ctx.settings,
        as_of=ctx.as_of,
        now=ctx.now,
    )


async def _submit_leave_request(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    return await submit_leave_request(
        args["preview_token"],
        ctx.idempotency_key(),
        hris=ctx.hris,
        settings=ctx.settings,
        nonce_store=ctx.nonce_store,
        idempotency_store=ctx.idempotency_store,
        audit_log=ctx.audit_log,
        as_of=ctx.as_of,
        now=ctx.now,
    )


async def _decide_leave_request(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    return await decide_leave_request(
        args["request_id"],
        args["employee_id"],
        ctx.acting_employee_id,
        args["decision"],
        ctx.idempotency_key(),
        hris=ctx.hris,
        idempotency_store=ctx.idempotency_store,
        audit_log=ctx.audit_log,
        as_of=ctx.as_of,
        now=ctx.now,
    )


async def _list_pending_approvals(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    return await list_pending_approvals(ctx.acting_employee_id, hris=ctx.hris, now=ctx.now)


async def _answer_hr_question(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    return await answer_hr_question(
        args["question"],
        ctx.acting_employee_id,
        hris=ctx.hris,
        knowledge_store=ctx.knowledge_store,
        gap_log=ctx.gap_log,
        now=ctx.now,
    )


async def _submit_daily_checkin(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    return await submit_daily_checkin(
        ctx.acting_employee_id,
        args["accomplishments"],
        args["blockers"],
        args["rating"],
        ctx.idempotency_key(),
        hris=ctx.hris,
        dashboard=ctx.dashboard,
        idempotency_store=ctx.idempotency_store,
        audit_log=ctx.audit_log,
        now=ctx.now,
    )


async def _list_missing_checkins(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    return await list_missing_checkins(
        ctx.acting_employee_id, hris=ctx.hris, dashboard=ctx.dashboard, as_of=ctx.as_of
    )


async def _get_team_summary(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    return await get_team_summary(
        ctx.acting_employee_id, hris=ctx.hris, dashboard=ctx.dashboard, as_of=ctx.as_of
    )


async def _calculate_gratuity(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    return await calculate_gratuity(
        ctx.acting_employee_id,
        args["basic_salary"],
        args["reason"],
        hris=ctx.hris,
        as_of=ctx.as_of,
    )


AGENT_TOOLS: list[AgentTool] = [
    AgentTool(
        ToolSpec(
            name="get_leave_balance",
            description="Get the current employee's annual leave balance.",
            parameters_schema={
                "type": "object",
                "properties": {"leave_type": {"type": "string", "enum": ["annual"]}},
                "required": ["leave_type"],
            },
        ),
        _get_leave_balance,
    ),
    AgentTool(
        ToolSpec(
            name="preview_leave_request",
            description=(
                "Preview an annual leave request before submitting -- shows the working days, "
                "balance impact, and who will approve it. Always call this before "
                "submit_leave_request; never submit without a preview the user has confirmed."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "leave_type": {"type": "string", "enum": ["annual"]},
                    "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "required": ["leave_type", "start_date", "end_date"],
            },
        ),
        _preview_leave_request,
    ),
    AgentTool(
        ToolSpec(
            name="submit_leave_request",
            description=(
                "Submit a previously previewed leave request. preview_token must come from a "
                "preview_leave_request call the user has explicitly confirmed in this "
                "conversation -- never invent or reuse a token from a different request."
            ),
            parameters_schema={
                "type": "object",
                "properties": {"preview_token": {"type": "string"}},
                "required": ["preview_token"],
            },
        ),
        _submit_leave_request,
    ),
    AgentTool(
        ToolSpec(
            name="decide_leave_request",
            description=(
                "Approve or reject a pending leave request the current user is the approver for."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "request_id": {"type": "string"},
                    "employee_id": {
                        "type": "string",
                        "description": "The employee whose request this is (not the approver).",
                    },
                    "decision": {"type": "string", "enum": ["approved", "rejected"]},
                },
                "required": ["request_id", "employee_id", "decision"],
            },
        ),
        _decide_leave_request,
    ),
    AgentTool(
        ToolSpec(
            name="list_pending_approvals",
            description="List the current user's pending leave-approval requests as a manager.",
            parameters_schema={"type": "object", "properties": {}},
        ),
        _list_pending_approvals,
    ),
    AgentTool(
        ToolSpec(
            name="answer_hr_question",
            description=(
                "Answer a general HR policy question (transfers, certificates, visas, etc.) "
                "from the SOP knowledge base."
            ),
            parameters_schema={
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        ),
        _answer_hr_question,
    ),
    AgentTool(
        ToolSpec(
            name="submit_daily_checkin",
            description=(
                "Submit the current user's daily check-in (accomplishments, blockers, a 1-5 "
                "rating)."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "accomplishments": {"type": "string"},
                    "blockers": {"type": "string"},
                    "rating": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                "required": ["accomplishments", "blockers", "rating"],
            },
        ),
        _submit_daily_checkin,
    ),
    AgentTool(
        ToolSpec(
            name="list_missing_checkins",
            description="List the current user's direct reports who haven't checked in today.",
            parameters_schema={"type": "object", "properties": {}},
        ),
        _list_missing_checkins,
    ),
    AgentTool(
        ToolSpec(
            name="get_team_summary",
            description=(
                "Summarize the current user's direct reports' check-ins for the current week."
            ),
            parameters_schema={"type": "object", "properties": {}},
        ),
        _get_team_summary,
    ),
    AgentTool(
        ToolSpec(
            name="calculate_gratuity",
            description=(
                "Estimate the current user's end-of-service gratuity. Not available for every "
                "country/reason combination -- if the tool returns GRATUITY_NOT_MODELED, say so "
                "plainly and suggest escalating to HR/payroll rather than estimating it yourself."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "basic_salary": {"type": "number"},
                    "reason": {
                        "type": "string",
                        "enum": [
                            "resignation",
                            "termination",
                            "termination_for_cause",
                            "retirement",
                            "death_or_disability",
                        ],
                    },
                },
                "required": ["basic_salary", "reason"],
            },
        ),
        _calculate_gratuity,
    ),
]

TOOLS_BY_NAME: dict[str, AgentTool] = {tool.spec.name: tool for tool in AGENT_TOOLS}
