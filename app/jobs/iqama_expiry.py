from datetime import date, datetime
from typing import Any

from app.core.iqama_alerts import IqamaAlertLog
from app.domain.iqama import days_until_expiry, needs_iqama_alert
from app.integrations.ports import HRISPort

# Iqama is Saudi residency-permit terminology; no other modelled country
# has this compliance concept, so the scan is intentionally scoped to
# one country rather than iterating COUNTRY_POLICIES generically.
_IQAMA_COUNTRY = "KSA"


async def run_iqama_expiry_check(
    *, hris: HRISPort, alert_log: IqamaAlertLog, as_of: date, now: datetime
) -> list[dict[str, Any]]:
    """Scans every KSA employee with a recorded Iqama expiry date and logs
    an alert for anyone inside the warning window (or already expired).

    A plain, directly callable function, not something wired only into
    APScheduler internals -- app/core/scheduler.py calls this on a
    schedule, but tests and scripts/seed_demo.py call it directly, the
    same "tools are plain functions" shape used everywhere else here.
    """
    employees = await hris.list_employees_by_country(_IQAMA_COUNTRY)

    alerts = []
    for employee in employees:
        if employee.iqama_expiry_date is None:
            continue
        if not needs_iqama_alert(employee.iqama_expiry_date, as_of):
            continue

        remaining = days_until_expiry(employee.iqama_expiry_date, as_of)
        alert_log.record(
            employee.employee_id, employee.full_name, employee.iqama_expiry_date, remaining, now
        )
        alerts.append(
            {
                "employee_id": employee.employee_id,
                "full_name": employee.full_name,
                "expiry_date": employee.iqama_expiry_date.isoformat(),
                "days_remaining": remaining,
            }
        )
    return alerts
