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
from app.integrations.bamboohr.leave_types import LeaveTypeMappingError
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
    # Not an id: BambooHR only exposes the manager as a display name via
    # this field, so manager_id stays None rather than holding a name.
    assert employee.manager_id is None
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
    directory_route = respx.get(f"{_BASE_URL}/employees/directory").mock(
        return_value=httpx.Response(200, json=_load("employee_directory.json"))
    )
    # The directory only has enough to find the id; the full record
    # (hireDate, birthDate, status, country) comes from a second call.
    employee_route = respx.get(f"{_BASE_URL}/employees/88").mock(
        return_value=httpx.Response(200, json=_load("employee_88.json"))
    )

    employee = await adapter.find_employee_by_phone("+966500000099")

    assert employee is not None
    assert employee.employee_id == "88"
    assert employee.full_name == "Omar Khalid"
    assert employee.employment_start_date == date(2015, 1, 1)
    assert employee.status == "active"
    assert directory_route.call_count == 1
    assert employee_route.call_count == 1


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
    respx.get(f"{_BASE_URL}/meta/time_off/types").mock(
        return_value=httpx.Response(200, json=_load("time_off_types.json"))
    )
    respx.get(f"{_BASE_URL}/time_off/requests").mock(
        return_value=httpx.Response(200, json=_load("time_off_requests_142.json"))
    )

    # "annual" is the domain key; resolving it to "Annual Leave/Holiday"
    # (this tenant's actual configured name) is the thing being tested.
    taken = await adapter.get_time_off_taken(
        "142", "annual", since=date(2026, 1, 1), until=date(2026, 12, 31)
    )

    # 5 days approved; the 2-day request is still "requested", not counted.
    assert taken == 5.0


@respx.mock
async def test_get_time_off_taken_bounds_the_query_by_the_until_date(
    adapter: BambooHRAdapter,
) -> None:
    # Caught against the live account: this call used to query through
    # date.max regardless of what "until" the caller actually wanted,
    # which let an approved request from a *later* leave year count
    # against the current one (see docs/ROADMAP.md). Only a request whose
    # query params match this exact [since, until] window is mocked --
    # if the adapter ever reverts to an unbounded query, respx has
    # nothing else registered and this fails loudly instead of silently
    # summing whatever an unbounded call happens to return.
    respx.get(f"{_BASE_URL}/meta/time_off/types").mock(
        return_value=httpx.Response(200, json=_load("time_off_types.json"))
    )
    respx.get(
        f"{_BASE_URL}/time_off/requests",
        params={"employeeId": "142", "start": "2026-01-01", "end": "2026-12-31"},
    ).mock(return_value=httpx.Response(200, json=_load("time_off_requests_142.json")))

    taken = await adapter.get_time_off_taken(
        "142", "annual", since=date(2026, 1, 1), until=date(2026, 12, 31)
    )

    assert taken == 5.0


@respx.mock
async def test_get_time_off_taken_raises_when_mapping_does_not_match_the_tenant(
    adapter: BambooHRAdapter,
) -> None:
    respx.get(f"{_BASE_URL}/meta/time_off/types").mock(
        return_value=httpx.Response(200, json={"timeOffTypes": [{"id": "1", "name": "Vacation"}]})
    )

    with pytest.raises(LeaveTypeMappingError):
        await adapter.get_time_off_taken(
            "142", "annual", since=date(2026, 1, 1), until=date(2026, 12, 31)
        )


@respx.mock
async def test_create_time_off_request_maps_the_created_request(
    adapter: BambooHRAdapter,
) -> None:
    respx.get(f"{_BASE_URL}/meta/time_off/types").mock(
        return_value=httpx.Response(200, json=_load("time_off_types.json"))
    )
    created_raw = _load("time_off_requests_142.json")[1]
    create_route = respx.put(f"{_BASE_URL}/employees/142/time_off/request").mock(
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
    # The outgoing payload used the resolved BambooHR type id (confirmed
    # live -- timeOffTypeName is not a real field), not the domain key.
    sent_body = json.loads(create_route.calls.last.request.content)
    assert sent_body["timeOffTypeId"] == "78"
    assert sent_body["amount"] == {"unit": "days", "amount": "2"}


@respx.mock
async def test_decide_time_off_request_maps_the_updated_status(
    adapter: BambooHRAdapter,
) -> None:
    # Confirmed live: this endpoint responds 200 with an empty body, not
    # the updated request -- the adapter must follow up to get real state.
    status_route = respx.put(f"{_BASE_URL}/time_off/requests/5001/status").mock(
        return_value=httpx.Response(200, json={})
    )
    updated_raw = _load("time_off_requests_142.json")[0]
    updated_raw["status"] = {
        "status": "approved",
        "lastChanged": "2026-05-22",
        "lastChangedByUserId": "88",
    }
    updated_raw["id"] = "5001"
    respx.get(f"{_BASE_URL}/time_off/requests").mock(
        return_value=httpx.Response(200, json=[updated_raw])
    )

    request = await adapter.decide_time_off_request("5001", "approved", decided_by="88")

    assert status_route.call_count == 1
    assert request.status == "approved"
    assert request.decided_by == "88"


@respx.mock
async def test_list_pending_approvals_filters_by_manager(adapter: BambooHRAdapter) -> None:
    # No id-based manager field exists: this resolves manager 88's own
    # name first, then matches it against the directory's `supervisor`
    # strings -- the shape BambooHR actually gives us.
    respx.get(f"{_BASE_URL}/employees/88").mock(
        return_value=httpx.Response(200, json=_load("employee_88.json"))
    )
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
    # Sara (142) manages no one in the directory -- querying her own id
    # as "manager" must come back empty, not everyone's requests.
    respx.get(f"{_BASE_URL}/employees/142").mock(
        return_value=httpx.Response(200, json=_load("employee_142.json"))
    )
    respx.get(f"{_BASE_URL}/time_off/requests").mock(
        return_value=httpx.Response(200, json=[_load("time_off_requests_142.json")[1]])
    )
    respx.get(f"{_BASE_URL}/employees/directory").mock(
        return_value=httpx.Response(200, json=_load("employee_directory.json"))
    )

    pending = await adapter.list_pending_approvals("142")

    assert pending == []


@respx.mock
async def test_list_pending_approvals_returns_empty_for_an_unresolvable_manager(
    adapter: BambooHRAdapter,
) -> None:
    respx.get(f"{_BASE_URL}/employees/does-not-exist").mock(return_value=httpx.Response(404))

    pending = await adapter.list_pending_approvals("does-not-exist")

    assert pending == []


@respx.mock
async def test_get_manager_resolves_the_reportsto_name_to_a_full_employee(
    adapter: BambooHRAdapter,
) -> None:
    respx.get(f"{_BASE_URL}/employees/142").mock(
        return_value=httpx.Response(200, json=_load("employee_142.json"))
    )
    respx.get(f"{_BASE_URL}/employees/directory").mock(
        return_value=httpx.Response(200, json=_load("employee_directory.json"))
    )
    respx.get(f"{_BASE_URL}/employees/88").mock(
        return_value=httpx.Response(200, json=_load("employee_88.json"))
    )

    manager = await adapter.get_manager("142")

    assert manager is not None
    assert manager.employee_id == "88"
    assert manager.full_name == "Omar Khalid"


@respx.mock
async def test_get_manager_returns_none_when_reportsto_is_absent(
    adapter: BambooHRAdapter,
) -> None:
    respx.get(f"{_BASE_URL}/employees/88").mock(
        return_value=httpx.Response(200, json=_load("employee_88.json"))
    )

    # employee_88.json has no reportsTo (Omar Khalid has no manager).
    assert await adapter.get_manager("88") is None


@respx.mock
async def test_get_manager_returns_none_when_the_name_matches_no_directory_entry(
    adapter: BambooHRAdapter,
) -> None:
    employee_with_unmatched_manager = dict(_load("employee_142.json"))
    employee_with_unmatched_manager["reportsTo"] = "Nobody In The Directory"
    respx.get(f"{_BASE_URL}/employees/142").mock(
        return_value=httpx.Response(200, json=employee_with_unmatched_manager)
    )
    respx.get(f"{_BASE_URL}/employees/directory").mock(
        return_value=httpx.Response(200, json=_load("employee_directory.json"))
    )

    assert await adapter.get_manager("142") is None


@respx.mock
async def test_list_direct_reports_matches_supervisor_name_in_the_directory(
    adapter: BambooHRAdapter,
) -> None:
    respx.get(f"{_BASE_URL}/employees/88").mock(
        return_value=httpx.Response(200, json=_load("employee_88.json"))
    )
    respx.get(f"{_BASE_URL}/employees/directory").mock(
        return_value=httpx.Response(200, json=_load("employee_directory.json"))
    )

    reports = await adapter.list_direct_reports("88")

    assert reports == ["142"]


@respx.mock
async def test_list_employees_by_country_scans_the_directory_and_filters(
    adapter: BambooHRAdapter,
) -> None:
    respx.get(f"{_BASE_URL}/employees/directory").mock(
        return_value=httpx.Response(200, json=_load("employee_directory.json"))
    )
    respx.get(f"{_BASE_URL}/employees/142").mock(
        return_value=httpx.Response(200, json=_load("employee_142.json"))
    )
    respx.get(f"{_BASE_URL}/employees/88").mock(
        return_value=httpx.Response(200, json=_load("employee_88.json"))
    )

    employees = await adapter.list_employees_by_country("KSA")

    assert sorted(e.employee_id for e in employees) == ["142", "88"]
    assert all(e.iqama_expiry_date is None for e in employees)


@respx.mock
async def test_list_employees_by_country_returns_empty_for_an_unrepresented_country(
    adapter: BambooHRAdapter,
) -> None:
    respx.get(f"{_BASE_URL}/employees/directory").mock(
        return_value=httpx.Response(200, json=_load("employee_directory.json"))
    )
    respx.get(f"{_BASE_URL}/employees/142").mock(
        return_value=httpx.Response(200, json=_load("employee_142.json"))
    )
    respx.get(f"{_BASE_URL}/employees/88").mock(
        return_value=httpx.Response(200, json=_load("employee_88.json"))
    )

    assert await adapter.list_employees_by_country("Jordan") == []


@respx.mock
async def test_list_direct_reports_returns_empty_for_an_unresolvable_manager(
    adapter: BambooHRAdapter,
) -> None:
    respx.get(f"{_BASE_URL}/employees/does-not-exist").mock(return_value=httpx.Response(404))

    assert await adapter.list_direct_reports("does-not-exist") == []


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
