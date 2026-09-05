import dataclasses
import itertools
from datetime import UTC, date, datetime
from typing import Literal

from app.domain.models import Employee, TimeOffRequest, TimeOffRequestDraft, TimeOffStatus
from app.integrations.ports import AmbiguousEmployeeError


class InMemoryHRISAdapter:
    """Dict-backed HRISPort implementation for tests and the offline demo.

    Pure storage and retrieval -- no entitlement math, no calendar rules.
    """

    def __init__(self) -> None:
        self._employees: dict[str, Employee] = {}
        self._requests: dict[str, TimeOffRequest] = {}
        self._request_ids = itertools.count(1)

    def seed_employee(self, employee: Employee) -> None:
        self._employees[employee.employee_id] = employee

    def seed_time_off_request(self, request: TimeOffRequest) -> None:
        # For tests that need to control requested_at directly (an SLA
        # check, say) -- create_time_off_request always stamps "now".
        self._requests[request.request_id] = request

    async def get_employee(self, employee_id: str) -> Employee | None:
        return self._employees.get(employee_id)

    async def find_employee_by_phone(self, phone_number: str) -> Employee | None:
        matches = [e for e in self._employees.values() if e.phone_number == phone_number]
        if len(matches) > 1:
            raise AmbiguousEmployeeError(phone_number, [e.employee_id for e in matches])
        return matches[0] if matches else None

    async def get_time_off_taken(self, employee_id: str, leave_type: str, since: date) -> float:
        return sum(
            request.working_days
            for request in self._requests.values()
            if request.employee_id == employee_id
            and request.leave_type == leave_type
            and request.status == "approved"
            and request.start_date >= since
        )

    async def create_time_off_request(self, draft: TimeOffRequestDraft) -> TimeOffRequest:
        request_id = str(next(self._request_ids))
        request = TimeOffRequest(
            request_id=request_id,
            employee_id=draft.employee_id,
            leave_type=draft.leave_type,
            start_date=draft.start_date,
            end_date=draft.end_date,
            working_days=draft.working_days,
            status="pending",
            requested_at=datetime.now(UTC),
        )
        self._requests[request_id] = request
        return request

    async def get_time_off_requests(
        self,
        employee_id: str,
        status: TimeOffStatus | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[TimeOffRequest]:
        results = [r for r in self._requests.values() if r.employee_id == employee_id]
        if status is not None:
            results = [r for r in results if r.status == status]
        if start is not None:
            # Overlap, not containment: a stored request counts if it ends
            # on/after the window's start and starts on/before its end.
            results = [r for r in results if r.end_date >= start]
        if end is not None:
            results = [r for r in results if r.start_date <= end]
        return results

    async def decide_time_off_request(
        self, request_id: str, decision: Literal["approved", "rejected"], decided_by: str
    ) -> TimeOffRequest:
        existing = self._requests[request_id]
        updated = dataclasses.replace(
            existing, status=decision, decided_by=decided_by, decided_at=datetime.now(UTC)
        )
        self._requests[request_id] = updated
        return updated

    async def list_pending_approvals(self, manager_id: str) -> list[TimeOffRequest]:
        return [
            request
            for request in self._requests.values()
            if request.status == "pending"
            and (employee := self._employees.get(request.employee_id)) is not None
            and employee.manager_id == manager_id
        ]

    async def get_manager(self, employee_id: str) -> Employee | None:
        employee = self._employees.get(employee_id)
        if employee is None or employee.manager_id is None:
            return None
        return self._employees.get(employee.manager_id)

    async def list_direct_reports(self, manager_id: str) -> list[str]:
        return [e.employee_id for e in self._employees.values() if e.manager_id == manager_id]

    async def list_employees_by_country(self, country: str) -> list[Employee]:
        return [e for e in self._employees.values() if e.country == country]
