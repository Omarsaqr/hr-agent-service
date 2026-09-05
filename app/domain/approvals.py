from datetime import datetime, timedelta

from app.domain.models import EmployeeStatus


def needs_escalation(
    manager_status: EmployeeStatus, manager_is_on_leave: bool, manager_is_requester: bool
) -> bool:
    """Whether the direct manager can't approve, so the skip-level ladder
    applies. Pure decision given the facts; gathering those facts (is the
    manager on leave right now? are they the requester?) needs HRIS
    calls, so that lives in the tool layer, not here.
    """
    return manager_status != "active" or manager_is_on_leave or manager_is_requester


def is_sla_breached(requested_at: datetime, now: datetime, sla_hours: int = 48) -> bool:
    return (now - requested_at) > timedelta(hours=sla_hours)
