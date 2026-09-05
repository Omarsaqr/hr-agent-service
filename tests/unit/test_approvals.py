from datetime import UTC, datetime

from app.domain.approvals import is_sla_breached, needs_escalation


def test_active_manager_not_on_leave_not_requester_needs_no_escalation() -> None:
    result = needs_escalation("active", manager_is_on_leave=False, manager_is_requester=False)
    assert result is False


def test_inactive_manager_needs_escalation() -> None:
    result = needs_escalation("terminated", manager_is_on_leave=False, manager_is_requester=False)
    assert result is True


def test_manager_on_leave_needs_escalation() -> None:
    assert needs_escalation("active", manager_is_on_leave=True, manager_is_requester=False) is True


def test_manager_is_requester_needs_escalation() -> None:
    assert needs_escalation("active", manager_is_on_leave=False, manager_is_requester=True) is True


def test_sla_not_breached_just_under_48_hours() -> None:
    requested_at = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
    now = datetime(2026, 6, 3, 8, 59, tzinfo=UTC)

    assert is_sla_breached(requested_at, now) is False


def test_sla_breached_just_over_48_hours() -> None:
    requested_at = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
    now = datetime(2026, 6, 3, 9, 1, tzinfo=UTC)

    assert is_sla_breached(requested_at, now) is True
