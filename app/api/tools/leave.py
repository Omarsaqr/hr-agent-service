import logging
from datetime import date, datetime
from typing import Any

from app.config import Settings
from app.core.errors import ToolError
from app.core.preview_tokens import (
    TOKEN_TTL,
    NonceStore,
    PreviewTokenExpiredError,
    PreviewTokenFields,
    PreviewTokenInvalidError,
    PreviewTokenReusedError,
    issue,
    verify_and_consume,
)
from app.domain.calendar import COUNTRY_CALENDARS, working_days_between
from app.domain.countries import COUNTRY_POLICIES
from app.domain.entitlements import (
    age_in_years,
    annual_leave_balance,
    annual_leave_entitlement,
    completed_months_of_service,
    current_leave_year_start,
)
from app.integrations.ports import HRISPort

_SUPPORTED_LEAVE_TYPES = {"annual"}
_security_logger = logging.getLogger("app.security")


class BalanceChangedError(Exception):
    """Re-verification at submit time found the world no longer matches
    what preview showed -- a stale token, not an invalid one."""


def _employee_not_found() -> dict[str, Any]:
    return ToolError(
        code="EMPLOYEE_NOT_FOUND",
        message_en="I couldn't find an employee record for that id.",
        message_ar="لم أتمكن من العثور على سجل موظف بهذا المعرف.",
        recovery_hint="Confirm the employee id came from resolve_employee, not user input.",
    ).to_response()


def _country_not_supported(country: str) -> dict[str, Any]:
    return ToolError(
        code="COUNTRY_NOT_SUPPORTED",
        message_en=f"Leave policy for '{country}' isn't configured yet.",
        message_ar=f"لم يتم إعداد سياسة الإجازات لـ '{country}' بعد.",
        recovery_hint="Escalate to HR -- this country has no entitlement rules encoded.",
        data={"country": country},
    ).to_response()


def _leave_type_not_supported(leave_type: str) -> dict[str, Any]:
    return ToolError(
        code="LEAVE_TYPE_NOT_SUPPORTED",
        message_en=f"'{leave_type}' isn't available yet -- only annual leave is.",
        message_ar=f"'{leave_type}' غير متاح حاليًا -- الإجازة السنوية فقط متاحة.",
        recovery_hint="Only leave_type='annual' is supported today.",
        data={"leave_type": leave_type},
    ).to_response()


async def get_leave_balance(
    employee_id: str, leave_type: str, *, hris: HRISPort, as_of: date
) -> dict[str, Any]:
    employee = await hris.get_employee(employee_id)
    if employee is None:
        return _employee_not_found()

    policy = COUNTRY_POLICIES.get(employee.country)
    if policy is None:
        return _country_not_supported(employee.country)

    if leave_type not in _SUPPORTED_LEAVE_TYPES:
        return _leave_type_not_supported(leave_type)

    completed_months = completed_months_of_service(employee.employment_start_date, as_of)
    age = age_in_years(employee.birth_date, as_of) if employee.birth_date else None
    entitlement = annual_leave_entitlement(policy.annual_leave, completed_months, age)

    leave_year_start = current_leave_year_start(employee.employment_start_date, as_of)
    taken = await hris.get_time_off_taken(employee_id, leave_type, since=leave_year_start)
    balance = annual_leave_balance(entitlement, taken)

    citation = policy.annual_leave.citation
    message_en = (
        f"You have {balance:g} days of annual leave available "
        f"({entitlement:g} days entitled under {citation}, "
        f"{taken:g} taken since {leave_year_start.isoformat()})."
    )
    message_ar = (
        f"لديك {balance:g} يومًا من الإجازة السنوية المتاحة "
        f"({entitlement:g} يومًا مستحقًا بموجب {citation}، "
        f"تم أخذ {taken:g} منذ {leave_year_start.isoformat()})."
    )

    return {
        "ok": True,
        "data": {
            "balances": [
                {
                    "leave_type": leave_type,
                    "entitlement_days": entitlement,
                    "taken_days": taken,
                    "balance_days": balance,
                    "period_start": leave_year_start.isoformat(),
                    "citation": citation,
                }
            ]
        },
        "message_en": message_en,
        "message_ar": message_ar,
    }


async def preview_leave_request(
    employee_id: str,
    leave_type: str,
    start_date: date,
    end_date: date,
    *,
    hris: HRISPort,
    settings: Settings,
    as_of: date,
    now: datetime,
) -> dict[str, Any]:
    if end_date < start_date:
        return ToolError(
            code="INVALID_DATE_RANGE",
            message_en="The end date is before the start date.",
            message_ar="تاريخ الانتهاء قبل تاريخ البدء.",
            recovery_hint="Confirm the dates with the employee and try again.",
            data={"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        ).to_response()

    employee = await hris.get_employee(employee_id)
    if employee is None:
        return _employee_not_found()

    policy = COUNTRY_POLICIES.get(employee.country)
    calendar = COUNTRY_CALENDARS.get(employee.country)
    if policy is None or calendar is None:
        return _country_not_supported(employee.country)

    if leave_type not in _SUPPORTED_LEAVE_TYPES:
        return _leave_type_not_supported(leave_type)

    working_days = working_days_between(calendar, start_date, end_date)

    completed_months = completed_months_of_service(employee.employment_start_date, as_of)
    age = age_in_years(employee.birth_date, as_of) if employee.birth_date else None
    entitlement = annual_leave_entitlement(policy.annual_leave, completed_months, age)

    leave_year_start = current_leave_year_start(employee.employment_start_date, as_of)
    taken = await hris.get_time_off_taken(employee_id, leave_type, since=leave_year_start)
    balance_before = annual_leave_balance(entitlement, taken)
    balance_after = balance_before - working_days

    manager = await hris.get_manager(employee_id)
    if manager is None:
        return ToolError(
            code="APPROVER_NOT_FOUND",
            message_en="I couldn't find a manager to route this approval to.",
            message_ar="لم أتمكن من العثور على مدير لتوجيه هذه الموافقة إليه.",
            recovery_hint="Escalate to HR to confirm this employee's reporting line.",
        ).to_response()

    fields = PreviewTokenFields(
        employee_id=employee_id,
        leave_type=leave_type,
        country=employee.country,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        working_days=working_days,
        balance_before=balance_before,
        balance_after=balance_after,
        approver_id=manager.employee_id,
    )
    token = issue(fields, secret=settings.preview_token_secret.get_secret_value(), now=now)
    token_expires_at = now + TOKEN_TTL

    message_en = (
        f"You have {balance_before:g} days of annual leave available. This request "
        f"({start_date.isoformat()} to {end_date.isoformat()}, {working_days:g} working days) "
        f"would leave you with {balance_after:g} days remaining. "
        f"It will go to {manager.full_name} for approval."
    )
    message_ar = (
        f"لديك {balance_before:g} يومًا من الإجازة السنوية المتاحة. سيترك هذا الطلب "
        f"({start_date.isoformat()} إلى {end_date.isoformat()}، {working_days:g} أيام عمل) "
        f"رصيدك {balance_after:g} يومًا، وسيُرسل إلى {manager.full_name} للموافقة."
    )

    return {
        "ok": True,
        "preview_token": token,
        "token_expires_at": token_expires_at.isoformat(),
        "data": {
            "employee_id": employee_id,
            "leave_type": leave_type,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "working_days": working_days,
            "entitlement_days": entitlement,
            "taken_days": taken,
            "balance_before": balance_before,
            "balance_after": balance_after,
            "approver": {"employee_id": manager.employee_id, "full_name": manager.full_name},
        },
        "message_en": message_en,
        "message_ar": message_ar,
    }


async def verify_preview_for_submission(
    token: str,
    *,
    hris: HRISPort,
    settings: Settings,
    nonce_store: NonceStore,
    as_of: date,
    now: datetime,
) -> dict[str, Any]:
    """Signature, freshness, single-use, then a full re-check against live
    data. Returns the verified token payload on success, or a structured
    ToolError response on any failure -- the actual submit tool (commit
    10) can return a failure result to the agent as-is.
    """
    try:
        return await _verify_preview(
            token, hris=hris, settings=settings, nonce_store=nonce_store, as_of=as_of, now=now
        )
    except PreviewTokenExpiredError:
        return ToolError(
            code="PREVIEW_EXPIRED",
            message_en="This preview has expired.",
            message_ar="انتهت صلاحية هذه المعاينة.",
            recovery_hint="Call preview_leave_request again to get current numbers, then retry.",
        ).to_response()
    except PreviewTokenReusedError:
        return ToolError(
            code="PREVIEW_ALREADY_USED",
            message_en="This preview has already been submitted.",
            message_ar="تم إرسال هذه المعاينة بالفعل.",
            recovery_hint="If another submission is needed, call preview_leave_request again.",
        ).to_response()
    except PreviewTokenInvalidError as exc:
        # exc.reason is for this log line only -- never in the response,
        # or an attacker probing signatures could use the difference to
        # learn which field broke.
        _security_logger.warning("rejected preview token: %s", exc.reason)
        return ToolError(
            code="PREVIEW_INVALID",
            message_en="This preview token isn't valid.",
            message_ar="رمز المعاينة هذا غير صالح.",
            recovery_hint="Call preview_leave_request again to get a valid token.",
        ).to_response()
    except BalanceChangedError:
        return ToolError(
            code="BALANCE_CHANGED",
            message_en="The numbers have changed since this preview was shown.",
            message_ar="تغيرت الأرقام منذ عرض هذه المعاينة.",
            recovery_hint=(
                "Call preview_leave_request again to see the current balance and "
                "approver before submitting."
            ),
        ).to_response()


async def _verify_preview(
    token: str,
    *,
    hris: HRISPort,
    settings: Settings,
    nonce_store: NonceStore,
    as_of: date,
    now: datetime,
) -> dict[str, Any]:
    payload = verify_and_consume(
        token,
        secret=settings.preview_token_secret.get_secret_value(),
        now=now,
        nonce_store=nonce_store,
    )

    employee = await hris.get_employee(payload["employee_id"])
    if employee is None or employee.country != payload["country"]:
        raise BalanceChangedError("employee record changed since preview")

    policy = COUNTRY_POLICIES.get(employee.country)
    calendar = COUNTRY_CALENDARS.get(employee.country)
    if policy is None or calendar is None:
        raise BalanceChangedError("country policy no longer available")

    # Re-resolve the approver from the signed id via a fresh lookup of
    # the employee's *current* manager -- never from a name, which was
    # never signed and isn't trusted as proof of anything. A manager
    # reassignment between preview and submit counts as the world having
    # changed, the same as a balance drift.
    current_manager = await hris.get_manager(payload["employee_id"])
    if current_manager is None or current_manager.employee_id != payload["approver_id"]:
        raise BalanceChangedError("approver has changed since preview")

    start_date = date.fromisoformat(payload["start_date"])
    end_date = date.fromisoformat(payload["end_date"])
    working_days_now = working_days_between(calendar, start_date, end_date)

    completed_months = completed_months_of_service(employee.employment_start_date, as_of)
    age = age_in_years(employee.birth_date, as_of) if employee.birth_date else None
    entitlement_now = annual_leave_entitlement(policy.annual_leave, completed_months, age)
    leave_year_start = current_leave_year_start(employee.employment_start_date, as_of)
    taken_now = await hris.get_time_off_taken(
        payload["employee_id"], payload["leave_type"], since=leave_year_start
    )
    balance_before_now = annual_leave_balance(entitlement_now, taken_now)

    balance_drifted = balance_before_now != payload["balance_before"]
    if working_days_now != payload["working_days"] or balance_drifted:
        raise BalanceChangedError(
            f"working_days {working_days_now} vs {payload['working_days']}, "
            f"balance_before {balance_before_now} vs {payload['balance_before']}"
        )

    return payload
