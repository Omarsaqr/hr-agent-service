from datetime import date

import pytest

from app.api.tools.gratuity import calculate_gratuity
from app.domain.models import Employee
from app.integrations.bamboohr.memory import InMemoryHRISAdapter

AS_OF = date(2026, 6, 1)


@pytest.fixture
def hris() -> InMemoryHRISAdapter:
    adapter = InMemoryHRISAdapter()
    adapter.seed_employee(
        Employee(
            employee_id="emp-ksa",
            full_name="Sara Ahmed",
            country="KSA",
            employment_start_date=date(2019, 6, 1),  # exactly 7 years
            status="active",
        )
    )
    adapter.seed_employee(
        Employee(
            employee_id="emp-uae",
            full_name="Omar Khalid",
            country="UAE",
            employment_start_date=date(2023, 6, 1),  # exactly 3 years
            status="active",
        )
    )
    adapter.seed_employee(
        Employee(
            employee_id="emp-egypt",
            full_name="Mona Said",
            country="Egypt",
            employment_start_date=date(2018, 6, 1),  # exactly 8 years
            status="active",
        )
    )
    adapter.seed_employee(
        Employee(
            employee_id="emp-jordan",
            full_name="Ali Hassan",
            country="Jordan",
            employment_start_date=date(2018, 6, 1),
            status="active",
        )
    )
    return adapter


async def test_calculate_gratuity_ksa_termination(hris: InMemoryHRISAdapter) -> None:
    result = await calculate_gratuity(
        "emp-ksa", 10_000, "termination", hris=hris, as_of=AS_OF
    )

    assert result["ok"] is True
    assert result["data"]["amount"] == pytest.approx(45_000)
    assert result["data"]["basis"] == "ksa_full_award"
    assert result["message_ar"]


async def test_calculate_gratuity_uae_standard(hris: InMemoryHRISAdapter) -> None:
    result = await calculate_gratuity(
        "emp-uae", 9_000, "resignation", hris=hris, as_of=AS_OF
    )

    assert result["ok"] is True
    assert result["data"]["amount"] == pytest.approx(18_900)


async def test_calculate_gratuity_egypt_retirement(hris: InMemoryHRISAdapter) -> None:
    result = await calculate_gratuity(
        "emp-egypt", 8_000, "retirement", hris=hris, as_of=AS_OF
    )

    assert result["ok"] is True
    assert result["data"]["amount"] == pytest.approx(44_000)


async def test_calculate_gratuity_egypt_resignation_is_not_modeled(
    hris: InMemoryHRISAdapter,
) -> None:
    result = await calculate_gratuity(
        "emp-egypt", 8_000, "resignation", hris=hris, as_of=AS_OF
    )

    assert result["ok"] is False
    assert result["code"] == "GRATUITY_NOT_MODELED"


async def test_calculate_gratuity_jordan_is_not_modeled(hris: InMemoryHRISAdapter) -> None:
    result = await calculate_gratuity(
        "emp-jordan", 5_000, "termination", hris=hris, as_of=AS_OF
    )

    assert result["ok"] is False
    assert result["code"] == "GRATUITY_NOT_MODELED"


async def test_calculate_gratuity_unknown_employee(hris: InMemoryHRISAdapter) -> None:
    result = await calculate_gratuity(
        "does-not-exist", 5_000, "termination", hris=hris, as_of=AS_OF
    )

    assert result["ok"] is False
    assert result["code"] == "EMPLOYEE_NOT_FOUND"
