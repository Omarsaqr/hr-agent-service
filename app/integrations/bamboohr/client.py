from typing import Any

import httpx

from app.integrations.bamboohr.retry import request_with_retry

_EMPLOYEE_FIELDS = "firstName,lastName,hireDate,birthDate,status,mobilePhone,country,reportsTo"
# BambooHR defaults several endpoints (the directory, notably) to XML;
# every call asks for JSON explicitly rather than relying on a default
# that differs by endpoint.
_JSON_HEADERS = {"Accept": "application/json"}


class BambooHRClient:
    """Talks BambooHR's wire format only -- no domain types cross this boundary."""

    def __init__(self, subdomain: str, api_key: str, http_client: httpx.AsyncClient) -> None:
        self._base_url = f"https://api.bamboohr.com/api/gateway.php/{subdomain}/v1"
        # BambooHR's documented convention: API key as the Basic Auth
        # username, literal "x" as the password.
        self._auth = httpx.BasicAuth(api_key, "x")
        self._http = http_client

    async def get_employee(self, employee_id: str) -> dict[str, Any] | None:
        response = await request_with_retry(
            lambda: self._http.get(
                f"{self._base_url}/employees/{employee_id}",
                params={"fields": _EMPLOYEE_FIELDS},
                headers=_JSON_HEADERS,
                auth=self._auth,
            ),
            idempotent=True,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    async def get_employee_directory(self) -> list[dict[str, Any]]:
        # BambooHR has no "search by phone" endpoint; the directory call
        # is the closest primitive, filtered client-side in the adapter.
        response = await request_with_retry(
            lambda: self._http.get(
                f"{self._base_url}/employees/directory", headers=_JSON_HEADERS, auth=self._auth
            ),
            idempotent=True,
        )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        return body.get("employees", [])  # type: ignore[no-any-return]

    async def get_time_off_requests(
        self, employee_id: str, start: str, end: str
    ) -> list[dict[str, Any]]:
        response = await request_with_retry(
            lambda: self._http.get(
                f"{self._base_url}/time_off/requests",
                params={"employeeId": employee_id, "start": start, "end": end},
                headers=_JSON_HEADERS,
                auth=self._auth,
            ),
            idempotent=True,
        )
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    async def get_all_pending_requests(self, start: str, end: str) -> list[dict[str, Any]]:
        response = await request_with_retry(
            lambda: self._http.get(
                f"{self._base_url}/time_off/requests",
                params={"start": start, "end": end, "status": "requested"},
                headers=_JSON_HEADERS,
                auth=self._auth,
            ),
            idempotent=True,
        )
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    async def get_all_time_off_requests(self, start: str, end: str) -> list[dict[str, Any]]:
        # Same endpoint as get_all_pending_requests, no status filter --
        # there is no per-request GET, so finding one specific request
        # after a status change means scanning this company-wide list.
        response = await request_with_retry(
            lambda: self._http.get(
                f"{self._base_url}/time_off/requests",
                params={"start": start, "end": end},
                headers=_JSON_HEADERS,
                auth=self._auth,
            ),
            idempotent=True,
        )
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    async def create_time_off_request(
        self, employee_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        response = await request_with_retry(
            lambda: self._http.put(
                f"{self._base_url}/employees/{employee_id}/time_off/request",
                json=payload,
                headers=_JSON_HEADERS,
                auth=self._auth,
            ),
            idempotent=False,
        )
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    async def get_time_off_types(self) -> list[dict[str, Any]]:
        response = await request_with_retry(
            lambda: self._http.get(
                f"{self._base_url}/meta/time_off/types", headers=_JSON_HEADERS, auth=self._auth
            ),
            idempotent=True,
        )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        return body.get("timeOffTypes", [])  # type: ignore[no-any-return]

    async def set_time_off_request_status(
        self, request_id: str, status: str, note: str | None
    ) -> dict[str, Any]:
        response = await request_with_retry(
            lambda: self._http.put(
                f"{self._base_url}/time_off/requests/{request_id}/status",
                json={"status": status, "note": note},
                headers=_JSON_HEADERS,
                auth=self._auth,
            ),
            idempotent=False,
        )
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]
