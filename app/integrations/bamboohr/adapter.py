from datetime import date, datetime
from typing import Any, Literal

from app.domain.models import (
    Employee,
    EmployeeStatus,
    TimeOffRequest,
    TimeOffRequestDraft,
    TimeOffStatus,
)
from app.integrations.bamboohr.cache import TTLCache
from app.integrations.bamboohr.client import BambooHRClient
from app.integrations.ports import AmbiguousEmployeeError

# BambooHR reports work country by name, not the codes countries.toml keys
# on. This table is the one place that mismatch is resolved.
_COUNTRY_NAME_TO_CODE = {
    "Saudi Arabia": "KSA",
    "United Arab Emirates": "UAE",
    "Egypt": "Egypt",
    "Jordan": "Jordan",
}

_EMPLOYEE_STATUS_FROM_BAMBOOHR: dict[str, EmployeeStatus] = {
    "Active": "active",
    "Inactive": "terminated",
}

# BambooHR's five statuses collapse onto our four -- "superseded" (an
# older request replaced by a newer one) has no domain equivalent, so it
# reads as cancelled rather than inventing a fifth status nothing else
# handles.
_TIME_OFF_STATUS_FROM_BAMBOOHR: dict[str, TimeOffStatus] = {
    "requested": "pending",
    "approved": "approved",
    "denied": "rejected",
    "canceled": "cancelled",
    "superseded": "cancelled",
}
_TIME_OFF_STATUS_TO_BAMBOOHR = {"approved": "approved", "rejected": "denied"}

_EMPLOYEE_CACHE_TTL_SECONDS = 300.0


class BambooHRAdapter:
    """HRISPort implementation. The only file besides client.py that knows
    BambooHR's field names -- everything it returns is a domain dataclass.
    """

    def __init__(self, client: BambooHRClient) -> None:
        self._client = client
        # Balances and requests are never cached: a stale employee record
        # is harmless, a stale balance tells someone they have days
        # they've already used.
        self._employee_cache: TTLCache[Employee | None] = TTLCache(_EMPLOYEE_CACHE_TTL_SECONDS)

    async def get_employee(self, employee_id: str) -> Employee | None:
        hit, cached = self._employee_cache.get(f"id:{employee_id}")
        if hit:
            return cached

        raw = await self._client.get_employee(employee_id)
        employee = _map_employee(raw) if raw is not None else None
        self._employee_cache.set(f"id:{employee_id}", employee)
        return employee

    async def find_employee_by_phone(self, phone_number: str) -> Employee | None:
        hit, cached = self._employee_cache.get(f"phone:{phone_number}")
        if hit:
            return cached

        directory = await self._client.get_employee_directory()
        matches = [
            _map_employee(raw) for raw in directory if raw.get("mobilePhone") == phone_number
        ]
        if len(matches) > 1:
            raise AmbiguousEmployeeError(phone_number, [e.employee_id for e in matches])

        employee = matches[0] if matches else None
        self._employee_cache.set(f"phone:{phone_number}", employee)
        return employee

    async def get_time_off_taken(self, employee_id: str, leave_type: str, since: date) -> float:
        raw_requests = await self._client.get_time_off_requests(
            employee_id, start=since.isoformat(), end=date.max.isoformat()
        )
        return sum(
            float(raw["amount"]["amount"])
            for raw in raw_requests
            if raw["status"]["status"] == "approved" and raw["type"]["name"] == leave_type
        )

    async def create_time_off_request(self, draft: TimeOffRequestDraft) -> TimeOffRequest:
        payload = {
            "start": draft.start_date.isoformat(),
            "end": draft.end_date.isoformat(),
            "timeOffTypeName": draft.leave_type,
            "amount": draft.working_days,
        }
        raw = await self._client.create_time_off_request(draft.employee_id, payload)
        return _map_time_off_request(raw)

    async def get_time_off_requests(
        self,
        employee_id: str,
        status: TimeOffStatus | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[TimeOffRequest]:
        raw_requests = await self._client.get_time_off_requests(
            employee_id,
            start=(start or date.min).isoformat(),
            end=(end or date.max).isoformat(),
        )
        requests = [_map_time_off_request(raw) for raw in raw_requests]
        if status is not None:
            requests = [r for r in requests if r.status == status]
        return requests

    async def decide_time_off_request(
        self, request_id: str, decision: Literal["approved", "rejected"], decided_by: str
    ) -> TimeOffRequest:
        raw = await self._client.set_time_off_request_status(
            request_id, _TIME_OFF_STATUS_TO_BAMBOOHR[decision], note=None
        )
        return _map_time_off_request(raw)

    async def list_pending_approvals(self, manager_id: str) -> list[TimeOffRequest]:
        # No native "pending approvals for manager X" endpoint: pull all
        # pending requests company-wide and filter by the requester's
        # manager. Fine at mock scale; a real deployment at 50k employees
        # would want this pushed server-side or paginated.
        pending_raw = await self._client.get_all_pending_requests(
            start=date.min.isoformat(), end=date.max.isoformat()
        )
        requests = [_map_time_off_request(raw) for raw in pending_raw]

        reports_to_manager = set[str]()
        for raw in await self._client.get_employee_directory():
            if raw.get("reportsToId") == manager_id:
                reports_to_manager.add(raw["id"])

        return [r for r in requests if r.employee_id in reports_to_manager]


def _map_employee(raw: dict[str, Any]) -> Employee:
    return Employee(
        employee_id=raw["id"],
        full_name=f"{raw['firstName']} {raw['lastName']}",
        country=_COUNTRY_NAME_TO_CODE.get(raw.get("country", ""), raw.get("country", "")),
        employment_start_date=date.fromisoformat(raw["hireDate"]),
        # BambooHR's base status field has no probation concept; a real
        # integration would need a custom field or the job-info table.
        status=_EMPLOYEE_STATUS_FROM_BAMBOOHR.get(raw.get("status", ""), "terminated"),
        manager_id=raw.get("reportsToId"),
        phone_number=raw.get("mobilePhone"),
        birth_date=date.fromisoformat(raw["birthDate"]) if raw.get("birthDate") else None,
    )


def _map_time_off_request(raw: dict[str, Any]) -> TimeOffRequest:
    status_block = raw["status"]
    last_changed = status_block.get("lastChanged")
    return TimeOffRequest(
        request_id=raw["id"],
        employee_id=raw["employeeId"],
        leave_type=raw["type"]["name"],
        start_date=date.fromisoformat(raw["start"]),
        end_date=date.fromisoformat(raw["end"]),
        working_days=float(raw["amount"]["amount"]),
        status=_TIME_OFF_STATUS_FROM_BAMBOOHR.get(status_block["status"], "pending"),
        requested_at=datetime.fromisoformat(raw["created"]),
        decided_by=status_block.get("lastChangedByUserId"),
        decided_at=datetime.fromisoformat(last_changed) if last_changed else None,
    )
