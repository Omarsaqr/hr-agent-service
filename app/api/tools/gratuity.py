from datetime import date
from typing import Any

from app.core.errors import ToolError, employee_not_found
from app.core.i18n import to_arabic_indic_numerals
from app.domain.entitlements import years_of_service
from app.domain.gratuity import (
    GratuityResult,
    SeparationReason,
    egypt_retirement_gratuity,
    ksa_gratuity,
    uae_gratuity,
)
from app.integrations.ports import HRISPort


def _not_modeled(country: str, reason: SeparationReason) -> dict[str, Any]:
    return ToolError(
        code="GRATUITY_NOT_MODELED",
        message_en=(
            f"Gratuity for '{country}' on {reason.replace('_', ' ')} isn't computed by this "
            "system -- see docs/ROADMAP.md for why."
        ),
        message_ar=f"لا يحسب هذا النظام مكافأة نهاية الخدمة لـ '{country}' في حالة {reason}.",
        recovery_hint="Escalate to HR/payroll for a manual calculation.",
        data={"country": country, "reason": reason},
    ).to_response()


async def calculate_gratuity(
    employee_id: str,
    basic_salary: float,
    reason: SeparationReason,
    *,
    hris: HRISPort,
    as_of: date,
) -> dict[str, Any]:
    """basic_salary is caller-supplied, not fetched from HRIS: no
    compensation endpoint has been verified against a live BambooHR
    account (see docs/ROADMAP.md), and this tool's job is the
    computation, not sourcing the wage figure.
    """
    employee = await hris.get_employee(employee_id)
    if employee is None:
        return employee_not_found()

    tenure_years = years_of_service(employee.employment_start_date, as_of)

    result: GratuityResult
    if employee.country == "KSA":
        result = ksa_gratuity(basic_salary, tenure_years, reason)
    elif employee.country == "UAE":
        result = uae_gratuity(basic_salary, tenure_years)
    elif employee.country == "Egypt":
        if reason != "retirement":
            return _not_modeled(employee.country, reason)
        result = egypt_retirement_gratuity(basic_salary, tenure_years)
    else:
        return _not_modeled(employee.country, reason)

    amount_text = f"{result.amount:,.2f}"
    message_en = (
        f"Estimated gratuity: {amount_text} (basic salary {basic_salary:,.2f}, "
        f"{tenure_years:.1f} years of service, {reason.replace('_', ' ')}) under {result.citation}."
    )
    message_ar = (
        f"مكافأة نهاية الخدمة التقديرية: {to_arabic_indic_numerals(amount_text)} "
        f"(الراتب الأساسي {to_arabic_indic_numerals(f'{basic_salary:,.2f}')}، "
        f"{to_arabic_indic_numerals(f'{tenure_years:.1f}')} سنوات خدمة) بموجب {result.citation}."
    )

    return {
        "ok": True,
        "data": {
            "employee_id": employee_id,
            "country": employee.country,
            "basic_salary": basic_salary,
            "years_of_service": tenure_years,
            "reason": reason,
            "amount": result.amount,
            "basis": result.basis,
            "citation": result.citation,
        },
        "message_en": message_en,
        "message_ar": message_ar,
    }
