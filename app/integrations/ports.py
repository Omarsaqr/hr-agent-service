from datetime import date
from typing import Literal, Protocol, runtime_checkable

from app.domain.models import (
    CheckinRecord,
    Employee,
    TimeOffRequest,
    TimeOffRequestDraft,
    TimeOffStatus,
)


class AmbiguousEmployeeError(Exception):
    """Raised when a phone number matches more than one employee record."""

    def __init__(self, phone_number: str, matched_employee_ids: list[str]) -> None:
        super().__init__(f"{phone_number!r} matched multiple employees: {matched_employee_ids}")
        self.phone_number = phone_number
        self.matched_employee_ids = matched_employee_ids


@runtime_checkable
class HRISPort(Protocol):
    async def get_employee(self, employee_id: str) -> Employee | None: ...

    async def find_employee_by_phone(self, phone_number: str) -> Employee | None:
        """phone_number must be E.164; raises AmbiguousEmployeeError on more than one match."""
        ...

    async def get_time_off_taken(self, employee_id: str, leave_type: str, since: date) -> float:
        """Days of `leave_type` taken since `since` -- domain/ computes entitlement and balance."""
        ...

    async def create_time_off_request(self, draft: TimeOffRequestDraft) -> TimeOffRequest: ...

    async def get_time_off_requests(
        self,
        employee_id: str,
        status: TimeOffStatus | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[TimeOffRequest]: ...

    async def decide_time_off_request(
        self, request_id: str, decision: Literal["approved", "rejected"], decided_by: str
    ) -> TimeOffRequest: ...

    async def list_pending_approvals(self, manager_id: str) -> list[TimeOffRequest]: ...

    async def get_manager(self, employee_id: str) -> Employee | None:
        """The employee's direct manager, resolved to a full Employee record."""
        ...


@runtime_checkable
class DashboardPort(Protocol):
    async def append_checkin(self, checkin: CheckinRecord) -> None: ...

    async def get_checkins(
        self, employee_ids: list[str], start: date, end: date
    ) -> list[CheckinRecord]:
        """One row per (employee_id, date): latest submission wins over earlier ones."""
        ...
