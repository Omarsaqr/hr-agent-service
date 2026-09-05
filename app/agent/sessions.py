from dataclasses import dataclass, field

from app.integrations.llm.ports import Message


@dataclass
class ChatSession:
    session_id: str
    employee_id: str
    history: list[Message] = field(default_factory=list)


class SessionStore:
    """In-process, in-memory only -- conversation history doesn't survive
    a process restart or exist outside this one process's memory. Fine
    for a demo/take-home; a real multi-instance deployment would need a
    shared store (Redis, a database table) instead.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, ChatSession] = {}

    def get_or_create(self, session_id: str, employee_id: str) -> ChatSession:
        session = self._sessions.get(session_id)
        if session is None:
            session = ChatSession(session_id=session_id, employee_id=employee_id)
            self._sessions[session_id] = session
        return session
