from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.core.audit import AuditLog
from app.core.errors import ToolError, employee_not_found
from app.core.idempotency import IdempotencyStore, compute_request_fingerprint
from app.domain.checkins import (
    MAX_RATING,
    MIN_RATING,
    is_valid_rating,
    missing_employee_ids,
    summarize_team_week,
    week_bounds,
)
from app.domain.models import CheckinRecord
from app.integrations.ports import DashboardPort, HRISPort

# The company's operating timezone, not the server's or the caller's --
# "today" for a check-in is a business-calendar question, decided once,
# here, rather than left to whatever timezone the request happened to
# arrive in.
_COMPANY_TIMEZONE = ZoneInfo("Asia/Riyadh")


async def submit_daily_checkin(
    employee_id: str,
    accomplishments: str,
    blockers: str,
    rating: int,
    idempotency_key: str,
    *,
    hris: HRISPort,
    dashboard: DashboardPort,
    idempotency_store: IdempotencyStore,
    audit_log: AuditLog,
    now: datetime,
) -> dict[str, Any]:
    employee = await hris.get_employee(employee_id)
    if employee is None:
        return employee_not_found()

    if not is_valid_rating(rating):
        return ToolError(
            code="INVALID_RATING",
            message_en=f"Rating must be between {MIN_RATING} and {MAX_RATING}.",
            message_ar=f"يجب أن يكون التقييم بين {MIN_RATING} و {MAX_RATING}.",
            recovery_hint=f"Ask for a rating from {MIN_RATING} to {MAX_RATING} and resubmit.",
            data={"rating": rating},
        ).to_response()

    fingerprint = compute_request_fingerprint(
        "submit_daily_checkin",
        {
            "employee_id": employee_id,
            "accomplishments": accomplishments,
            "blockers": blockers,
            "rating": rating,
        },
    )
    checkin_date = now.astimezone(_COMPANY_TIMEZONE).date()

    async def do_submit() -> dict[str, Any]:
        checkin = CheckinRecord(
            employee_id=employee_id,
            checkin_date=checkin_date,
            accomplishments=accomplishments,
            blockers=blockers,
            rating=rating,
            submitted_by=employee_id,
            submitted_at=now,
            idempotency_key=idempotency_key,
        )
        try:
            await dashboard.append_checkin(checkin)
        except Exception:
            audit_log.record(
                actor_id=employee_id,
                action="submit_daily_checkin",
                status="failed",
                now=now,
                details={"reason": "dashboard_write_failed"},
            )
            raise

        audit_log.record(
            actor_id=employee_id,
            action="submit_daily_checkin",
            status="success",
            now=now,
            details={"checkin_date": checkin_date.isoformat()},
        )
        return {
            "ok": True,
            "data": {"checkin_date": checkin_date.isoformat()},
            "message_en": "Check-in recorded for today. Thanks!",
            "message_ar": "تم تسجيل تحديثك اليومي. شكرًا لك!",
        }

    try:
        return await idempotency_store.run(idempotency_key, fingerprint, now, do_submit)
    except Exception:
        return ToolError(
            code="UPSTREAM_UNAVAILABLE",
            message_en="I couldn't reach the dashboard to record this check-in.",
            message_ar="تعذر الوصول إلى لوحة المتابعة لتسجيل هذا التحديث.",
            recovery_hint="Try again shortly, or escalate to HR if this persists.",
        ).to_response()


async def list_missing_checkins(
    manager_id: str, *, hris: HRISPort, dashboard: DashboardPort, as_of: date
) -> dict[str, Any]:
    manager = await hris.get_employee(manager_id)
    if manager is None:
        return employee_not_found()

    team_ids = await hris.list_direct_reports(manager_id)
    checkins = await dashboard.get_checkins(team_ids, as_of, as_of) if team_ids else []
    missing_ids = missing_employee_ids(team_ids, checkins)
    missing = await _resolve_names(missing_ids, hris)

    if not missing:
        message_en = "Everyone on your team has checked in today."
        message_ar = "جميع أعضاء فريقك سجّلوا تحديثهم اليوم."
    else:
        names = ", ".join(m["full_name"] for m in missing)
        message_en = (
            f"{len(missing)} of {len(team_ids)} direct report(s) haven't checked in today: "
            f"{names}."
        )
        message_ar = (
            f"{len(missing)} من {len(team_ids)} من مرؤوسيك المباشرين لم يسجلوا تحديثهم اليوم: "
            f"{names}."
        )

    return {
        "ok": True,
        "data": {"date": as_of.isoformat(), "missing_employees": missing},
        "message_en": message_en,
        "message_ar": message_ar,
    }


async def get_team_summary(
    manager_id: str, *, hris: HRISPort, dashboard: DashboardPort, as_of: date
) -> dict[str, Any]:
    manager = await hris.get_employee(manager_id)
    if manager is None:
        return employee_not_found()

    team_ids = await hris.list_direct_reports(manager_id)
    week_start, week_end = week_bounds(as_of)

    if not team_ids:
        return {
            "ok": True,
            "data": {
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
                "expected_count": 0,
                "submitted_count": 0,
                "average_rating": None,
                "missing_employees": [],
                "checkins": [],
            },
            "message_en": "You have no direct reports to summarize.",
            "message_ar": "ليس لديك مرؤوسون مباشرون لتلخيص تحديثاتهم.",
        }

    checkins = await dashboard.get_checkins(team_ids, week_start, week_end)
    summary = summarize_team_week(team_ids, checkins, week_start, week_end)
    missing = await _resolve_names(summary.missing_employee_ids, hris)

    submitted_count = len(team_ids) - len(missing)
    average_text = f"{summary.average_rating:.1f}" if summary.average_rating is not None else "n/a"
    message_en = (
        f"{submitted_count} of {len(team_ids)} direct report(s) checked in this week "
        f"({week_start.isoformat()} to {week_end.isoformat()}), average rating {average_text}."
    )
    message_ar = (
        f"{submitted_count} من {len(team_ids)} من مرؤوسيك المباشرين سجّلوا تحديثهم هذا الأسبوع "
        f"({week_start.isoformat()} إلى {week_end.isoformat()})، متوسط التقييم {average_text}."
    )

    return {
        "ok": True,
        "data": {
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "expected_count": len(team_ids),
            "submitted_count": submitted_count,
            "average_rating": summary.average_rating,
            "missing_employees": missing,
            "checkins": [
                {
                    "employee_id": c.employee_id,
                    "checkin_date": c.checkin_date.isoformat(),
                    "rating": c.rating,
                    "accomplishments": c.accomplishments,
                    "blockers": c.blockers,
                }
                for c in summary.checkins
            ],
        },
        "message_en": message_en,
        "message_ar": message_ar,
    }


async def _resolve_names(employee_ids: list[str], hris: HRISPort) -> list[dict[str, str]]:
    """Best-effort display names for a small, bounded id list (a direct-
    report team, never the whole company) -- sequential awaits, since at
    this scale the wall-clock cost of not parallelising is unmeasurable
    and not worth the extra complexity of asyncio.gather.
    """
    resolved = []
    for employee_id in employee_ids:
        employee = await hris.get_employee(employee_id)
        full_name = employee.full_name if employee is not None else employee_id
        resolved.append({"employee_id": employee_id, "full_name": full_name})
    return resolved
