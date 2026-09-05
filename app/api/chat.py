import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.agent.runtime import run_chat_turn
from app.agent.tools import ChatDeps
from app.config import Settings
from app.deps import (
    get_audit_log,
    get_dashboard_port,
    get_gap_log,
    get_hris_port,
    get_idempotency_store,
    get_knowledge_store,
    get_llm_port,
    get_nonce_store,
    get_session_store,
)

router = APIRouter()


class ChatRequest(BaseModel):
    employee_id: str
    message: str
    # None starts a new conversation; the response's session_id must be
    # sent back on subsequent turns for the agent to see prior history
    # (previews, confirmations) -- this is a plain in-memory session, not
    # a cookie or auth token.
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, http_request: Request) -> ChatResponse:
    # Settings is constructed once, at app startup (main.py), and hung
    # off app.state -- not rebuilt per request, though get_hris_port and
    # friends would still return the correctly-cached adapter either way
    # since they key off specific settings values, not object identity.
    settings: Settings = http_request.app.state.settings

    session_id = payload.session_id or str(uuid.uuid4())
    session = get_session_store().get_or_create(session_id, payload.employee_id)

    deps = ChatDeps(
        hris=get_hris_port(settings),
        dashboard=get_dashboard_port(settings),
        settings=settings,
        nonce_store=get_nonce_store(),
        idempotency_store=get_idempotency_store(),
        audit_log=get_audit_log(),
        knowledge_store=get_knowledge_store(),
        gap_log=get_gap_log(),
    )

    reply = await run_chat_turn(
        payload.message,
        session.history,
        llm=get_llm_port(settings),
        deps=deps,
        acting_employee_id=payload.employee_id,
        now=datetime.now(UTC),
        as_of=datetime.now(UTC).date(),
    )

    return ChatResponse(session_id=session_id, reply=reply)
