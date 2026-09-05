import json
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import quote

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.domain.models import CheckinRecord
from app.integrations.sheets.adapter import GoogleSheetsAdapter, HeaderMismatchError
from app.integrations.sheets.client import GoogleSheetsClient

_SPREADSHEET_ID = "fake-spreadsheet-id"
_TOKEN_URI = "https://oauth2.googleapis.com/token"
_BASE_URL = f"https://sheets.googleapis.com/v4/spreadsheets/{_SPREADSHEET_ID}"
_HEADER_ROW = [
    "employee_id",
    "checkin_date",
    "accomplishments",
    "blockers",
    "rating",
    "submitted_by",
    "submitted_at",
    "idempotency_key",
]


def _values_url(a1_range: str) -> str:
    return f"{_BASE_URL}/values/{quote(a1_range, safe='')}"


@pytest.fixture(scope="module")
def service_account_info() -> dict[str, Any]:
    # A throwaway keypair, not a real Google credential -- this exercises
    # the real JWT-signing code path (google.auth.jwt.encode + RSASigner)
    # without needing real Google Cloud access.
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return {
        "client_email": "fake@fake-project.iam.gserviceaccount.com",
        "private_key": pem,
        "private_key_id": "fake-key-id",
        "token_uri": _TOKEN_URI,
    }


@pytest.fixture
def adapter(service_account_info: dict[str, Any]) -> GoogleSheetsAdapter:
    client = GoogleSheetsClient(_SPREADSHEET_ID, service_account_info, httpx.AsyncClient())
    return GoogleSheetsAdapter(client, sheet_name="checkins")


def _mock_token_endpoint() -> respx.Route:
    return respx.post(_TOKEN_URI).mock(
        return_value=httpx.Response(200, json={"access_token": "fake-token", "expires_in": 3600})
    )


def _mock_header_row(headers: list[str] = _HEADER_ROW) -> respx.Route:
    return respx.get(_values_url("checkins!1:1")).mock(
        return_value=httpx.Response(200, json={"values": [headers]})
    )


def make_checkin(**overrides: object) -> CheckinRecord:
    defaults: dict[str, object] = {
        "employee_id": "emp-1",
        "checkin_date": date(2026, 6, 1),
        "accomplishments": "shipped the report",
        "blockers": "none",
        "rating": 4,
        "submitted_by": "lead-1",
        "submitted_at": datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
        "idempotency_key": "key-1",
    }
    defaults.update(overrides)
    return CheckinRecord(**defaults)  # type: ignore[arg-type]


@respx.mock
async def test_append_checkin_authenticates_and_appends_a_row(
    adapter: GoogleSheetsAdapter,
) -> None:
    token_route = _mock_token_endpoint()
    _mock_header_row()
    append_route = respx.post(f"{_values_url('checkins')}:append").mock(
        return_value=httpx.Response(200, json={})
    )

    await adapter.append_checkin(make_checkin())

    assert token_route.call_count == 1
    assert append_route.call_count == 1
    sent = append_route.calls[0].request
    assert sent.headers["Authorization"] == "Bearer fake-token"
    payload = json.loads(sent.content)
    assert payload["values"] == [
        ["emp-1", "2026-06-01", "shipped the report", "none", "4", "lead-1",
         "2026-06-01T09:00:00+00:00", "key-1"]
    ]


@respx.mock
async def test_access_token_is_reused_across_calls(adapter: GoogleSheetsAdapter) -> None:
    token_route = _mock_token_endpoint()
    _mock_header_row()
    respx.post(f"{_values_url('checkins')}:append").mock(return_value=httpx.Response(200, json={}))

    await adapter.append_checkin(make_checkin())
    await adapter.append_checkin(make_checkin())

    assert token_route.call_count == 1


@respx.mock
async def test_header_mismatch_raises_before_any_write(adapter: GoogleSheetsAdapter) -> None:
    _mock_token_endpoint()
    _mock_header_row(headers=["employee_id", "wrong_column"])
    append_route = respx.post(f"{_values_url('checkins')}:append").mock(
        return_value=httpx.Response(200, json={})
    )

    with pytest.raises(HeaderMismatchError):
        await adapter.append_checkin(make_checkin())

    assert append_route.call_count == 0


@respx.mock
async def test_get_checkins_filters_by_employee_and_date_range(
    adapter: GoogleSheetsAdapter,
) -> None:
    _mock_token_endpoint()
    _mock_header_row()
    respx.get(_values_url("checkins")).mock(
        return_value=httpx.Response(
            200,
            json={
                "values": [
                    _HEADER_ROW,
                    ["emp-1", "2026-06-01", "shipped x", "none", "4", "lead-1",
                     "2026-06-01T09:00:00+00:00", "key-1"],
                    ["emp-2", "2026-06-01", "shipped y", "none", "3", "lead-1",
                     "2026-06-01T09:00:00+00:00", "key-2"],
                    ["emp-1", "2026-06-02", "shipped z", "none", "5", "lead-1",
                     "2026-06-02T09:00:00+00:00", "key-3"],
                ]
            },
        )
    )

    result = await adapter.get_checkins(["emp-1"], start=date(2026, 6, 1), end=date(2026, 6, 1))

    assert len(result) == 1
    assert result[0].accomplishments == "shipped x"


@respx.mock
async def test_get_checkins_keeps_only_the_latest_resubmission(
    adapter: GoogleSheetsAdapter,
) -> None:
    _mock_token_endpoint()
    _mock_header_row()
    respx.get(_values_url("checkins")).mock(
        return_value=httpx.Response(
            200,
            json={
                "values": [
                    _HEADER_ROW,
                    ["emp-1", "2026-06-01", "first draft", "none", "3", "lead-1",
                     "2026-06-01T09:00:00+00:00", "key-1"],
                    ["emp-1", "2026-06-01", "final version", "none", "5", "lead-1",
                     "2026-06-01T17:00:00+00:00", "key-2"],
                ]
            },
        )
    )

    result = await adapter.get_checkins(["emp-1"], start=date(2026, 6, 1), end=date(2026, 6, 1))

    assert len(result) == 1
    assert result[0].accomplishments == "final version"
    assert result[0].rating == 5


@respx.mock
async def test_get_checkins_tolerates_a_row_with_a_trimmed_trailing_column(
    adapter: GoogleSheetsAdapter,
) -> None:
    # Sheets trims trailing empty cells from a row -- a blank
    # idempotency_key comes back as a 7-element row, not 8 with a
    # trailing empty string. This must not crash.
    _mock_token_endpoint()
    _mock_header_row()
    respx.get(_values_url("checkins")).mock(
        return_value=httpx.Response(
            200,
            json={
                "values": [
                    _HEADER_ROW,
                    ["emp-1", "2026-06-01", "shipped x", "none", "4", "lead-1",
                     "2026-06-01T09:00:00+00:00"],
                ]
            },
        )
    )

    result = await adapter.get_checkins(["emp-1"], start=date(2026, 6, 1), end=date(2026, 6, 1))

    assert len(result) == 1
    assert result[0].idempotency_key == ""


@respx.mock
async def test_get_checkins_skips_a_blank_row(adapter: GoogleSheetsAdapter) -> None:
    _mock_token_endpoint()
    _mock_header_row()
    respx.get(_values_url("checkins")).mock(
        return_value=httpx.Response(200, json={"values": [_HEADER_ROW, []]})
    )

    result = await adapter.get_checkins(["emp-1"], start=date(2026, 6, 1), end=date(2026, 6, 30))

    assert result == []
