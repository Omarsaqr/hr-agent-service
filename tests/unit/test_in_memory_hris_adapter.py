from datetime import date

import pytest

from app.domain.models import Employee, TimeOffRequestDraft
from app.integrations.bamboohr.memory import InMemoryHRISAdapter
from app.integrations.ports import AmbiguousEmployeeError


def make_employee(**overrides: object) -> Employee:
    defaults: dict[str, object] = {
        "employee_id": "emp-1",
        "full_name": "Sara Ahmed",
        "country": "SA",
        "employment_start_date": date(2020, 1, 1),
        "status": "active",
    }
    defaults.update(overrides)
    return Employee(**defaults)  # type: ignore[arg-type]


async def test_get_employee_returns_none_when_missing() -> None:
    adapter = InMemoryHRISAdapter()

    assert await adapter.get_employee("missing") is None


async def test_get_employee_returns_seeded_record() -> None:
    adapter = InMemoryHRISAdapter()
    adapter.seed_employee(make_employee())

    result = await adapter.get_employee("emp-1")

    assert result is not None
    assert result.full_name == "Sara Ahmed"


async def test_find_employee_by_phone_returns_none_when_no_match() -> None:
    adapter = InMemoryHRISAdapter()

    assert await adapter.find_employee_by_phone("+966500000000") is None


async def test_find_employee_by_phone_returns_the_single_match() -> None:
    adapter = InMemoryHRISAdapter()
    adapter.seed_employee(make_employee(phone_number="+966500000000"))

    result = await adapter.find_employee_by_phone("+966500000000")

    assert result is not None
    assert result.employee_id == "emp-1"


async def test_find_employee_by_phone_raises_on_multiple_matches() -> None:
    adapter = InMemoryHRISAdapter()
    adapter.seed_employee(
        make_employee(employee_id="emp-1", phone_number="+966500000000")
    )
    adapter.seed_employee(
        make_employee(employee_id="emp-2", phone_number="+966500000000")
    )

    with pytest.raises(AmbiguousEmployeeError) as exc_info:
        await adapter.find_employee_by_phone("+966500000000")

    assert set(exc_info.value.matched_employee_ids) == {"emp-1", "emp-2"}


async def test_create_and_list_time_off_requests() -> None:
    adapter = InMemoryHRISAdapter()
    draft = TimeOffRequestDraft(
        employee_id="emp-1",
        leave_type="annual",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 5),
        working_days=5,
    )

    created = await adapter.create_time_off_request(draft)
    listed = await adapter.get_time_off_requests("emp-1")

    assert created.status == "pending"
    assert listed == [created]


async def test_get_time_off_requests_filters_by_status() -> None:
    adapter = InMemoryHRISAdapter()
    draft = TimeOffRequestDraft(
        employee_id="emp-1",
        leave_type="annual",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 5),
        working_days=5,
    )
    created = await adapter.create_time_off_request(draft)
    await adapter.decide_time_off_request(created.request_id, "approved", decided_by="mgr-1")

    pending = await adapter.get_time_off_requests("emp-1", status="pending")
    approved = await adapter.get_time_off_requests("emp-1", status="approved")

    assert pending == []
    assert len(approved) == 1
    assert approved[0].status == "approved"


async def test_get_time_off_requests_filters_overlapping_range() -> None:
    adapter = InMemoryHRISAdapter()
    await adapter.create_time_off_request(
        TimeOffRequestDraft(
            employee_id="emp-1",
            leave_type="annual",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 5),
            working_days=5,
        )
    )

    overlapping = await adapter.get_time_off_requests(
        "emp-1", start=date(2026, 6, 4), end=date(2026, 6, 10)
    )
    outside = await adapter.get_time_off_requests(
        "emp-1", start=date(2026, 7, 1), end=date(2026, 7, 10)
    )

    assert len(overlapping) == 1
    assert outside == []


async def test_request_ending_on_the_new_start_date_is_a_conflict() -> None:
    adapter = InMemoryHRISAdapter()
    await adapter.create_time_off_request(
        TimeOffRequestDraft(
            employee_id="emp-1",
            leave_type="annual",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 5),
            working_days=5,
        )
    )

    # Shared boundary day counts as overlap, not a gap.
    conflicts = await adapter.get_time_off_requests(
        "emp-1", start=date(2026, 6, 5), end=date(2026, 6, 8)
    )

    assert len(conflicts) == 1


async def test_get_time_off_taken_sums_only_approved_requests_since_date() -> None:
    adapter = InMemoryHRISAdapter()
    old_request = await adapter.create_time_off_request(
        TimeOffRequestDraft(
            employee_id="emp-1",
            leave_type="annual",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 3),
            working_days=3,
        )
    )
    await adapter.decide_time_off_request(old_request.request_id, "approved", decided_by="mgr-1")

    recent_request = await adapter.create_time_off_request(
        TimeOffRequestDraft(
            employee_id="emp-1",
            leave_type="annual",
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 5),
            working_days=5,
        )
    )
    await adapter.decide_time_off_request(
        recent_request.request_id, "approved", decided_by="mgr-1"
    )

    pending_request = await adapter.create_time_off_request(
        TimeOffRequestDraft(
            employee_id="emp-1",
            leave_type="annual",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 2),
            working_days=2,
        )
    )

    taken = await adapter.get_time_off_taken("emp-1", "annual", since=date(2026, 1, 1))

    assert taken == 5
    assert pending_request.status == "pending"


async def test_decide_time_off_request_does_not_mutate_the_original_object() -> None:
    adapter = InMemoryHRISAdapter()
    created = await adapter.create_time_off_request(
        TimeOffRequestDraft(
            employee_id="emp-1",
            leave_type="annual",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 5),
            working_days=5,
        )
    )

    updated = await adapter.decide_time_off_request(
        created.request_id, "approved", decided_by="mgr-1"
    )

    assert created.status == "pending"
    assert updated.status == "approved"
    assert updated.decided_by == "mgr-1"


async def test_list_pending_approvals_filters_by_manager_and_status() -> None:
    adapter = InMemoryHRISAdapter()
    adapter.seed_employee(make_employee(employee_id="emp-1", manager_id="mgr-1"))
    adapter.seed_employee(make_employee(employee_id="emp-2", manager_id="mgr-2"))

    request_for_mgr1 = await adapter.create_time_off_request(
        TimeOffRequestDraft(
            employee_id="emp-1",
            leave_type="annual",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 5),
            working_days=5,
        )
    )
    other_request = await adapter.create_time_off_request(
        TimeOffRequestDraft(
            employee_id="emp-2",
            leave_type="annual",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 5),
            working_days=5,
        )
    )
    await adapter.decide_time_off_request(other_request.request_id, "approved", decided_by="mgr-2")

    pending_for_mgr1 = await adapter.list_pending_approvals("mgr-1")

    assert pending_for_mgr1 == [request_for_mgr1]


async def test_get_manager_returns_the_seeded_managers_record() -> None:
    adapter = InMemoryHRISAdapter()
    adapter.seed_employee(make_employee(employee_id="emp-1", manager_id="mgr-1"))
    adapter.seed_employee(make_employee(employee_id="mgr-1", full_name="Manager One"))

    manager = await adapter.get_manager("emp-1")

    assert manager is not None
    assert manager.employee_id == "mgr-1"


async def test_get_manager_returns_none_when_employee_has_no_manager() -> None:
    adapter = InMemoryHRISAdapter()
    adapter.seed_employee(make_employee(employee_id="emp-1", manager_id=None))

    assert await adapter.get_manager("emp-1") is None


async def test_get_manager_returns_none_for_an_unknown_employee() -> None:
    adapter = InMemoryHRISAdapter()

    assert await adapter.get_manager("does-not-exist") is None


async def test_list_direct_reports_returns_ids_of_employees_reporting_to_the_manager() -> None:
    adapter = InMemoryHRISAdapter()
    adapter.seed_employee(make_employee(employee_id="mgr-1", manager_id=None))
    adapter.seed_employee(make_employee(employee_id="emp-1", manager_id="mgr-1"))
    adapter.seed_employee(make_employee(employee_id="emp-2", manager_id="mgr-1"))
    adapter.seed_employee(make_employee(employee_id="emp-3", manager_id="mgr-2"))

    reports = await adapter.list_direct_reports("mgr-1")

    assert sorted(reports) == ["emp-1", "emp-2"]


async def test_list_direct_reports_returns_empty_for_a_manager_with_no_reports() -> None:
    adapter = InMemoryHRISAdapter()
    adapter.seed_employee(make_employee(employee_id="mgr-1", manager_id=None))

    assert await adapter.list_direct_reports("mgr-1") == []
