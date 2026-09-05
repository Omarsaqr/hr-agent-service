import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.domain.models import TimeOffRequestDraft
from app.integrations.bamboohr.adapter import BambooHRAdapter
from app.integrations.bamboohr.client import BambooHRClient
from app.integrations.ports import AmbiguousEmployeeError

_FIXTURES = Path(__file__).parent.parent.parent / "app/integrations/bamboohr/fixtures"
_BASE_URL = "https://api.bamboohr.com/api/gateway.php/testco/v1"


def _load(name: str) -> Any:
    return json.loads((_FIXTURES / name).read_text())


@pytest.fixture
def adapter() -> BambooHRAdapter:
    client = BambooHRClient("testco", "fake-api-key", httpx.AsyncClient())
    return BambooHRAdapter(client)


@respx.mock
async def test_get_employee_maps_bamboohr_fields_to_the_domain_shape(
    adapter: BambooHRAdapter,
) -> None:
    respx.get(f"{_BASE_URL}/employees/142").mock(
        return_value=httpx.Response(200, json=_load("employee_142.json"))
    )

    employee = await adapter.get_employee("142")

    assert employee is not None
    assert employee.employee_id == "142"
    assert employee.full_name == "Sara Ahmed"
    assert employee.country == "KSA"  # BambooHR said "Saudi Arabia"
    assert employee.employment_start_date == date(2021, 11, 1)
    assert employee.status == "active"
    assert employee.manager_id == "88"
    assert employee.phone_number == "+966500000001"
    assert employee.birth_date == date(1990, 6, 15)


@respx.mock
async def test_get_employee_returns_none_on_404(adapter: BambooHRAdapter) -> None:
    respx.get(f"{_BASE_URL}/employees/999").mock(return_value=httpx.Response(404))

    assert await adapter.get_employee("999") is None


@respx.mock
async def test_get_employee_is_cached_on_the_second_call(adapter: BambooHRAdapter) -> None:
    route = respx.get(f"{_BASE_URL}/employees/142").mock(
        return_value=httpx.Response(200, json=_load("employee_142.json"))
    )

    await adapter.get_employee("142")
    await adapter.get_employee("142")

    assert route.call_count == 1


@respx.mock
async def test_find_employee_by_phone_maps_the_matching_directory_entry(
    adapter: BambooHRAdapter,
) -> None:
    respx.get(f"{_BASE_URL}/employees/directory").mock(
        return_value=httpx.Response(200, json=_load("employee_directory.json"))
    )

    employee = await adapter.find_employee_by_phone("+966500000099")

    assert employee is not None
    assert employee.employee_id == "88"
    assert employee.full_name == "Omar Khalid"
    assert employee.manager_id is None


@respx.mock
async def test_find_employee_by_phone_raises_on_more_than_one_match(
    adapter: BambooHRAdapter,
) -> None:
    directory = _load("employee_directory.json")
    assert isinstance(directory, dict)
    duplicate = dict(directory["employees"][0])
    duplicate["id"] = "999"
    directory["employees"].append(duplicate)
    respx.get(f"{_BASE_URL}/employees/directory").mock(
        return_value=httpx.Response(200, json=directory)
    )

    with pytest.raises(AmbiguousEmployeeError):
        await adapter.find_employee_by_phone("+966500000001")


@respx.mock
async def test_get_time_off_requests_maps_status_and_amount(adapter: BambooHRAdapter) -> None:
    respx.get(f"{_BASE_URL}/time_off/requests").mock(
        return_value=httpx.Response(200, json=_load("time_off_requests_142.json"))
    )

    requests = await adapter.get_time_off_requests("142")

    assert [r.status for r in requests] == ["approved", "pending"]
    assert requests[0].working_days == 5.0
    assert requests[0].leave_type == "annual"


@respx.mock
async def test_get_time_off_taken_sums_only_matching_approved_requests(
    adapter: BambooHRAdapter,
) -> None:
    respx.get(f"{_BASE_URL}/time_off/requests").mock(
        return_value=httpx.Response(200, json=_load("time_off_requests_142.json"))
    )

    taken = await adapter.get_time_off_taken("142", "annual", since=date(2026, 1, 1))

    # 5 days approved; the 2-day request is still "requested", not counted.
    assert taken == 5.0


@respx.mock
async def test_create_time_off_request_maps_the_created_request(
    adapter: BambooHRAdapter,
) -> None:
    created_raw = _load("time_off_requests_142.json")[1]
    respx.put(f"{_BASE_URL}/employees/142/time_off/request").mock(
        return_value=httpx.Response(201, json=created_raw)
    )

    request = await adapter.create_time_off_request(
        TimeOffRequestDraft(
            employee_id="142",
            leave_type="annual",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            working_days=2,
        )
    )

    assert request.request_id == "5002"
    assert request.status == "pending"


@respx.mock
async def test_decide_time_off_request_maps_the_updated_status(
    adapter: BambooHRAdapter,
) -> None:
    updated_raw = _load("time_off_requests_142.json")[0]
    updated_raw["status"] = {
        "status": "approved",
        "lastChanged": "2026-05-22T08:00:00",
        "lastChangedByUserId": "88",
    }
    respx.put(f"{_BASE_URL}/time_off/requests/5001/status").mock(
        return_value=httpx.Response(200, json=updated_raw)
    )

    request = await adapter.decide_time_off_request("5001", "approved", decided_by="88")

    assert request.status == "approved"
    assert request.decided_by == "88"


@respx.mock
async def test_list_pending_approvals_filters_by_manager(adapter: BambooHRAdapter) -> None:
    respx.get(f"{_BASE_URL}/time_off/requests").mock(
        return_value=httpx.Response(200, json=[_load("time_off_requests_142.json")[1]])
    )
    respx.get(f"{_BASE_URL}/employees/directory").mock(
        return_value=httpx.Response(200, json=_load("employee_directory.json"))
    )

    pending = await adapter.list_pending_approvals("88")

    assert [r.request_id for r in pending] == ["5002"]


@respx.mock
async def test_list_pending_approvals_excludes_other_managers_reports(
    adapter: BambooHRAdapter,
) -> None:
    respx.get(f"{_BASE_URL}/time_off/requests").mock(
        return_value=httpx.Response(200, json=[_load("time_off_requests_142.json")[1]])
    )
    respx.get(f"{_BASE_URL}/employees/directory").mock(
        return_value=httpx.Response(200, json=_load("employee_directory.json"))
    )

    pending = await adapter.list_pending_approvals("some-other-manager")

    assert pending == []


@respx.mock
async def test_get_time_off_requests_is_not_cached(adapter: BambooHRAdapter) -> None:
    route = respx.get(f"{_BASE_URL}/time_off/requests").mock(
        return_value=httpx.Response(200, json=_load("time_off_requests_142.json"))
    )

    await adapter.get_time_off_requests("142")
    await adapter.get_time_off_requests("142")

    # Unlike employee lookups, this must hit the network every time --
    # a stale balance is the failure mode the brief is explicit about.
    assert route.call_count == 2
