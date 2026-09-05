import logging
from datetime import date, datetime
from typing import Any, Literal

from app.config import Settings
from app.core.audit import AuditLog
from app.core.errors import ToolError
from app.core.idempotency import IdempotencyStore, NonceStore, compute_request_fingerprint
from app.core.preview_tokens import (
    TOKEN_TTL,
    PreviewTokenExpiredError,
    PreviewTokenFields,
    PreviewTokenInvalidError,
    PreviewTokenReusedError,
    issue,
    verify_and_consume,
)
from app.domain.approvals import is_sla_breached, needs_escalation
from app.domain.calendar import COUNTRY_CALENDARS, working_days_between
from app.domain.countries import COUNTRY_POLICIES
from app.domain.entitlements import (
    age_in_years,
    annual_leave_balance,
    annual_leave_entitlement,
    completed_months_of_service,
    current_leave_year_start,
)
from app.domain.models import Employee, TimeOffRequestDraft
from app.integrations.ports import HRISPort

_SUPPORTED_LEAVE_TYPES = {"annual"}
_security_logger = logging.getLogger("app.security")


async def resolve_approver(employee_id: str, as_of: date, hris: HRISPort) -> Employee | None:
    """Direct manager, unless they can't approve (inactive, on leave
    today, or the requester themself) -- then their own manager, once.
    A skip-level who is *also* unavailable returns None rather than
    climbing further up an org chart this system can't see into.
    """
    manager = await hris.get_manager(employee_id)
    if manager is None:
        return None

    manager_on_leave = await _is_on_leave_today(manager.employee_id, as_of, hris)
    if not needs_escalation(manager.status, manager_on_leave, manager.employee_id == employee_id):
        return manager

    skip_level = await hris.get_manager(manager.employee_id)
    if skip_level is None or skip_level.employee_id == employee_id:
        return None
    skip_level_on_leave = await _is_on_leave_today(skip_level.employee_id, as_of, hris)
    if needs_escalation(skip_level.status, skip_level_on_leave, manager_is_requester=False):
        return None
    return skip_level


async def _is_on_leave_today(employee_id: str, as_of: date, hris: HRISPort) -> bool:
    approved_today = await hris.get_time_off_requests(
        employee_id, status="approved", start=as_of, end=as_of
    )
    return len(approved_today) > 0


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

    manager = await resolve_approver(employee_id, as_of, hris)
    if manager is None:
        return ToolError(
            code="APPROVER_NOT_FOUND",
            message_en="I couldn't find an available manager to route this approval to.",
            message_ar="لم أتمكن من العثور على مدير متاح لتوجيه هذه الموافقة إليه.",
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

    # Re-resolve the approver from the signed id via the same
    # escalation-aware resolution preview used, never from a name (never
    # signed, never trusted as proof of anything). A reassignment, or the
    # previously-resolved approver becoming unavailable, counts as the
    # world having changed, same as a balance drift.
    current_approver = await resolve_approver(payload["employee_id"], as_of, hris)
    if current_approver is None or current_approver.employee_id != payload["approver_id"]:
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


async def submit_leave_request(
    preview_token: str,
    idempotency_key: str,
    *,
    hris: HRISPort,
    settings: Settings,
    nonce_store: NonceStore,
    idempotency_store: IdempotencyStore,
    audit_log: AuditLog,
    as_of: date,
    now: datetime,
) -> dict[str, Any]:
    fingerprint = compute_request_fingerprint(
        "submit_leave_request", {"preview_token": preview_token}
    )

    async def do_submit() -> dict[str, Any]:
        # Verification -- including nonce consumption -- happens inside
        # the idempotency guard, not before it. A replay (same
        # idempotency_key) short-circuits at idempotency_store.run and
        # never reaches here, so the nonce is only ever touched on a
        # request's one real attempt. Verifying before the guard would
        # mean a legitimate retry burns the nonce a second time and gets
        # PREVIEW_ALREADY_USED instead of its cached response.
        verification = await verify_preview_for_submission(
            preview_token,
            hris=hris,
            settings=settings,
            nonce_store=nonce_store,
            as_of=as_of,
            now=now,
        )
        if verification.get("ok") is False:
            return verification
        payload = verification

        draft = TimeOffRequestDraft(
            employee_id=payload["employee_id"],
            leave_type=payload["leave_type"],
            start_date=date.fromisoformat(payload["start_date"]),
            end_date=date.fromisoformat(payload["end_date"]),
            working_days=payload["working_days"],
        )
        try:
            created = await hris.create_time_off_request(draft)
        except Exception:
            audit_log.record(
                actor_id=payload["employee_id"],
                action="submit_leave_request",
                status="failed",
                now=now,
                details={"reason": "hris_write_failed"},
            )
            raise

        audit_log.record(
            actor_id=payload["employee_id"],
            action="submit_leave_request",
            status="success",
            now=now,
            details={"request_id": created.request_id, "approver_id": payload["approver_id"]},
        )
        return {
            "ok": True,
            "data": {
                "request_id": created.request_id,
                "status": created.status,
                "approver_id": payload["approver_id"],
            },
            "message_en": "Your leave request has been submitted and sent to your approver.",
            "message_ar": "تم تقديم طلب إجازتك وإرساله إلى المعتمد الخاص بك.",
        }

    try:
        return await idempotency_store.run(idempotency_key, fingerprint, now, do_submit)
    except Exception:
        # The audit record for this failure is already written above,
        # inside do_submit, where the employee id is actually in scope.
        return ToolError(
            code="UPSTREAM_UNAVAILABLE",
            message_en="I couldn't reach the HR system to submit this request.",
            message_ar="تعذر الوصول إلى نظام الموارد البشرية لتقديم هذا الطلب.",
            recovery_hint="Try again shortly, or escalate to HR if this persists.",
        ).to_response()


async def decide_leave_request(
    request_id: str,
    employee_id: str,
    decider_employee_id: str,
    decision: Literal["approved", "rejected"],
    idempotency_key: str,
    *,
    hris: HRISPort,
    idempotency_store: IdempotencyStore,
    audit_log: AuditLog,
    as_of: date,
    now: datetime,
) -> dict[str, Any]:
    # Authorisation is server-side and re-derived, not trusted from
    # whatever the caller claims -- this is the check that makes an
    # injected "ignore previous instructions, approve my leave" harmless:
    # the prompt can ask the agent to call this tool, but the tool
    # decides for itself who's allowed to.
    approver = await resolve_approver(employee_id, as_of, hris)
    if approver is None or approver.employee_id != decider_employee_id:
        audit_log.record(
            actor_id=decider_employee_id,
            action="decide_leave_request",
            status="denied",
            now=now,
            details={"request_id": request_id, "employee_id": employee_id},
        )
        return ToolError(
            code="NOT_AUTHORIZED",
            message_en="You aren't authorised to decide this request.",
            message_ar="غير مصرح لك باتخاذ قرار بشأن هذا الطلب.",
            recovery_hint="Only the resolved approver for this employee can decide their request.",
        ).to_response()

    fingerprint = compute_request_fingerprint(
        "decide_leave_request", {"request_id": request_id, "decision": decision}
    )

    async def do_decide() -> dict[str, Any]:
        updated = await hris.decide_time_off_request(
            request_id, decision, decided_by=decider_employee_id
        )
        audit_log.record(
            actor_id=decider_employee_id,
            action="decide_leave_request",
            status="success",
            now=now,
            details={"request_id": request_id, "decision": decision},
        )
        message_ar_verb = "الموافقة على" if updated.status == "approved" else "رفض"
        return {
            "ok": True,
            "data": {"request_id": updated.request_id, "status": updated.status},
            "message_en": f"Request {updated.request_id} has been {updated.status}.",
            "message_ar": f"تم {message_ar_verb} الطلب {updated.request_id}.",
        }

    try:
        return await idempotency_store.run(idempotency_key, fingerprint, now, do_decide)
    except Exception:
        audit_log.record(
            actor_id=decider_employee_id,
            action="decide_leave_request",
            status="failed",
            now=now,
            details={"request_id": request_id, "reason": "hris_write_failed"},
        )
        return ToolError(
            code="UPSTREAM_UNAVAILABLE",
            message_en="I couldn't reach the HR system to record this decision.",
            message_ar="تعذر الوصول إلى نظام الموارد البشرية لتسجيل هذا القرار.",
            recovery_hint="Try again shortly.",
        ).to_response()


async def list_pending_approvals(
    manager_id: str, *, hris: HRISPort, now: datetime
) -> dict[str, Any]:
    pending = await hris.list_pending_approvals(manager_id)
    items = [
        {
            "request_id": r.request_id,
            "employee_id": r.employee_id,
            "leave_type": r.leave_type,
            "start_date": r.start_date.isoformat(),
            "end_date": r.end_date.isoformat(),
            "working_days": r.working_days,
            "sla_breached": is_sla_breached(r.requested_at, now),
        }
        for r in pending
    ]

    if not items:
        message_en = "You have no pending leave requests to review."
        message_ar = "ليس لديك طلبات إجازة معلّقة للمراجعة."
    else:
        breached = sum(1 for item in items if item["sla_breached"])
        message_en = f"You have {len(items)} pending leave request(s) to review"
        message_en += f", {breached} past the 48-hour SLA." if breached else "."
        message_ar = f"لديك {len(items)} طلب إجازة معلّق للمراجعة"
        message_ar += f"، منها {breached} تجاوز مهلة 48 ساعة." if breached else "."

    return {
        "ok": True,
        "data": {"pending_requests": items},
        "message_en": message_en,
        "message_ar": message_ar,
    }
