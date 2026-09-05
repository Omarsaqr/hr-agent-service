from datetime import date

from app.domain.models import Employee


def test_birth_date_is_excluded_from_repr() -> None:
    employee = Employee(
        employee_id="emp-1",
        full_name="Sara Ahmed",
        country="EG",
        employment_start_date=date(2020, 1, 1),
        status="active",
        birth_date=date(1974, 3, 1),
    )

    assert "1974" not in repr(employee)


def test_iqama_expiry_date_is_excluded_from_repr() -> None:
    employee = Employee(
        employee_id="emp-1",
        full_name="Sara Ahmed",
        country="KSA",
        employment_start_date=date(2020, 1, 1),
        status="active",
        iqama_expiry_date=date(2026, 12, 25),
    )

    assert "2026-12-25" not in repr(employee)
