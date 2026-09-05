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
from app.integrations.bamboohr.leave_types import (
    BAMBOOHR_NAME_TO_DOMAIN_TYPE,
    LEAVE_TYPE_MAPPING,
    validate_leave_type_mapping,
)
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
        self._time_off_types: list[dict[str, Any]] | None = None

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

        # The directory has mobilePhone but not hireDate/birthDate/status/
        # country -- a directory-only Employee would carry silent Nones
        # for required-looking fields. Resolve the id here, then let
        # get_employee (already cached) fetch the full record.
        directory = await self._client.get_employee_directory()
        matching_ids = [raw["id"] for raw in directory if raw.get("mobilePhone") == phone_number]
        if len(matching_ids) > 1:
            raise AmbiguousEmployeeError(phone_number, matching_ids)

        employee = await self.get_employee(matching_ids[0]) if matching_ids else None
        self._employee_cache.set(f"phone:{phone_number}", employee)
        return employee

    async def get_time_off_taken(self, employee_id: str, leave_type: str, since: date) -> float:
        bamboohr_type_name = await self._resolve_bamboohr_leave_type_name(leave_type)
        raw_requests = await self._client.get_time_off_requests(
            employee_id, start=since.isoformat(), end=date.max.isoformat()
        )
        return sum(
            float(raw["amount"]["amount"])
            for raw in raw_requests
            if raw["status"]["status"] == "approved" and raw["type"]["name"] == bamboohr_type_name
        )

    async def create_time_off_request(self, draft: TimeOffRequestDraft) -> TimeOffRequest:
        type_id = await self._resolve_bamboohr_leave_type_id(draft.leave_type)
        payload = {
            "status": "requested",
            "start": draft.start_date.isoformat(),
            "end": draft.end_date.isoformat(),
            "timeOffTypeId": type_id,
            # BambooHR independently recomputes this against its own
            # configured schedule (confirmed live: a 2-day request came
            # back as 1 day once its own calendar was applied) -- what we
            # send is a starting point, not the number of record.
            # _map_time_off_request reports whatever the response says,
            # not this value.
            "amount": {"unit": "days", "amount": str(draft.working_days)},
        }
        raw = await self._client.create_time_off_request(draft.employee_id, payload)
        return _map_time_off_request(raw)

    async def _resolve_bamboohr_leave_type_name(self, domain_leave_type: str) -> str:
        await self._get_validated_time_off_types()
        return LEAVE_TYPE_MAPPING[domain_leave_type]

    async def _resolve_bamboohr_leave_type_id(self, domain_leave_type: str) -> str:
        bamboohr_name = await self._resolve_bamboohr_leave_type_name(domain_leave_type)
        types = await self._get_validated_time_off_types()
        return next(str(t["id"]) for t in types if t["name"] == bamboohr_name)

    async def _get_validated_time_off_types(self) -> list[dict[str, Any]]:
        if self._time_off_types is None:
            types = await self._client.get_time_off_types()
            validate_leave_type_mapping({t["name"] for t in types})
            self._time_off_types = types
        return self._time_off_types

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
        # Confirmed live: the status-change endpoint responds 200 with an
        # empty body, not the updated request. There is also no
        # per-request GET, so the only way to return a real, complete
        # TimeOffRequest (not a partial one guessed from what we already
        # had) is a follow-up company-wide fetch.
        await self._client.set_time_off_request_status(
            request_id, _TIME_OFF_STATUS_TO_BAMBOOHR[decision], note=None
        )
        all_requests = await self._client.get_all_time_off_requests(
            start=date.min.isoformat(), end=date.max.isoformat()
        )
        raw = next(r for r in all_requests if r["id"] == request_id)
        return _map_time_off_request(raw)

    async def list_pending_approvals(self, manager_id: str) -> list[TimeOffRequest]:
        # No native "pending approvals for manager X" endpoint, and no
        # id-based manager field either: the directory's only manager
        # reference is `supervisor`, a display name. Resolve the target
        # manager's own name via get_employee, then match that string
        # against each directory entry -- the same shape BambooHR
        # actually gives us, not the id-based shape assumed pre-verification.
        manager = await self.get_employee(manager_id)
        if manager is None:
            return []

        pending_raw = await self._client.get_all_pending_requests(
            start=date.min.isoformat(), end=date.max.isoformat()
        )
        requests = [_map_time_off_request(raw) for raw in pending_raw]

        direct_report_ids = {
            raw["id"]
            for raw in await self._client.get_employee_directory()
            if raw.get("supervisor") == manager.full_name
        }
        return [r for r in requests if r.employee_id in direct_report_ids]


def _map_employee(raw: dict[str, Any]) -> Employee:
    return Employee(
        employee_id=raw["id"],
        full_name=f"{raw['firstName']} {raw['lastName']}",
        country=_COUNTRY_NAME_TO_CODE.get(raw.get("country", ""), raw.get("country", "")),
        employment_start_date=date.fromisoformat(raw["hireDate"]),
        # BambooHR's base status field has no probation concept; a real
        # integration would need a custom field or the job-info table.
        status=_EMPLOYEE_STATUS_FROM_BAMBOOHR.get(raw.get("status", ""), "terminated"),
        # Not raw.get("reportsTo"): that field is a display name, not an
        # id, and manager_id would be lying about what it holds if it put
        # a name where callers expect something matching employee_id.
        # list_pending_approvals resolves manager relationships by name
        # directly, since that's the only thing BambooHR actually exposes.
        manager_id=None,
        phone_number=raw.get("mobilePhone"),
        birth_date=date.fromisoformat(raw["birthDate"]) if raw.get("birthDate") else None,
    )


def _map_time_off_request(raw: dict[str, Any]) -> TimeOffRequest:
    status_block = raw["status"]
    last_changed = status_block.get("lastChanged")
    bamboohr_type_name = raw["type"]["name"]
    return TimeOffRequest(
        request_id=raw["id"],
        employee_id=raw["employeeId"],
        # Falls back to the raw BambooHR name for a type with no mapping
        # entry (e.g. Bereavement) -- there's no domain key to translate
        # it to, so passing it through beats dropping it.
        leave_type=BAMBOOHR_NAME_TO_DOMAIN_TYPE.get(bamboohr_type_name, bamboohr_type_name),
        start_date=date.fromisoformat(raw["start"]),
        end_date=date.fromisoformat(raw["end"]),
        working_days=float(raw["amount"]["amount"]),
        status=_TIME_OFF_STATUS_FROM_BAMBOOHR.get(status_block["status"], "pending"),
        requested_at=datetime.fromisoformat(raw["created"]),
        decided_by=status_block.get("lastChangedByUserId"),
        decided_at=datetime.fromisoformat(last_changed) if last_changed else None,
    )
