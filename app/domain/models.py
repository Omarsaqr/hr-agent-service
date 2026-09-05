from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

EmployeeStatus = Literal["active", "probation", "terminated"]
TimeOffStatus = Literal["pending", "approved", "rejected", "cancelled"]
Language = Literal["en", "ar"]


@dataclass(frozen=True, slots=True)
class Employee:
    employee_id: str
    full_name: str
    country: str
    employment_start_date: date
    status: EmployeeStatus
    manager_id: str | None = None
    phone_number: str | None = None
    preferred_language: Language | None = None
    # Needed for Egypt's age-50 alternative entitlement threshold. Kept as
    # a date rather than a precomputed age: age is only correct as of a
    # specific `as_of`, and a cached int would go stale the day after it
    # was computed. repr=False keeps it out of logs and reprs; tool
    # response schemas and the audit log must not serialise it either --
    # this field never reaches the agent, only entitlements.py.
    birth_date: date | None = field(default=None, repr=False)
    # KSA-specific (Iqama is Saudi residency-permit terminology); None
    # everywhere else. repr=False for the same reason as birth_date --
    # a compliance-relevant date of record, not something that belongs
    # in a casual log line.
    iqama_expiry_date: date | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class TimeOffRequestDraft:
    employee_id: str
    leave_type: str
    start_date: date
    end_date: date
    # Computed by domain/calendar.py before the draft is built, not by the
    # adapter -- adapters store what they're given, they don't compute it.
    working_days: float


@dataclass(frozen=True, slots=True)
class TimeOffRequest:
    request_id: str
    employee_id: str
    leave_type: str
    start_date: date
    end_date: date
    working_days: float
    status: TimeOffStatus
    requested_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CheckinRecord:
    employee_id: str
    checkin_date: date
    accomplishments: str
    blockers: str
    rating: int
    submitted_by: str
    submitted_at: datetime
    idempotency_key: str
