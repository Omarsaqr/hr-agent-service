import base64
import sqlite3
from datetime import UTC, date, datetime

import pytest

from app.api.tools.leave import (
    get_leave_balance,
    preview_leave_request,
    verify_preview_for_submission,
)
from app.config import Settings
from app.core.preview_tokens import NonceStore
from app.domain.models import Employee, TimeOffRequestDraft
from app.integrations.bamboohr.memory import InMemoryHRISAdapter

AS_OF = date(2026, 6, 1)
NOW = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)


def make_settings() -> Settings:
    return Settings(_env_file=None, environment="test", preview_token_secret="test-secret")


@pytest.fixture
def hris() -> InMemoryHRISAdapter:
    adapter = InMemoryHRISAdapter()
    adapter.seed_employee(
        Employee(
            employee_id="emp-1",
            full_name="Sara Ahmed",
            country="KSA",
            employment_start_date=date(2020, 1, 1),
            status="active",
            manager_id="mgr-1",
        )
    )
    adapter.seed_employee(
        Employee(
            employee_id="mgr-1",
            full_name="Manager One",
            country="KSA",
            employment_start_date=date(2015, 1, 1),
            status="active",
        )
    )
    return adapter


async def _seed_approved_days(hris: InMemoryHRISAdapter, days: float) -> None:
    request = await hris.create_time_off_request(
        TimeOffRequestDraft(
            employee_id="emp-1",
            leave_type="annual",
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 3),
            working_days=days,
        )
    )
    await hris.decide_time_off_request(request.request_id, "approved", decided_by="mgr-1")


@pytest.fixture
def nonce_store() -> NonceStore:
    return NonceStore(sqlite3.connect(":memory:"))


async def test_get_leave_balance_computes_entitlement_minus_taken(
    hris: InMemoryHRISAdapter,
) -> None:
    await _seed_approved_days(hris, 3)

    result = await get_leave_balance("emp-1", "annual", hris=hris, as_of=AS_OF)

    assert result["ok"] is True
    balance = result["data"]["balances"][0]
    assert balance["entitlement_days"] == 30
    assert balance["taken_days"] == 3
    assert balance["balance_days"] == 27
    assert balance["period_start"] == "2026-01-01"
    assert "Art. 109" in balance["citation"]
    assert "27" in result["message_en"]
    assert result["message_ar"]  # non-empty; exact phrasing not pinned here


async def test_get_leave_balance_unknown_employee(hris: InMemoryHRISAdapter) -> None:
    result = await get_leave_balance("does-not-exist", "annual", hris=hris, as_of=AS_OF)

    assert result == {
        "ok": False,
        "code": "EMPLOYEE_NOT_FOUND",
        "message_en": result["message_en"],
        "message_ar": result["message_ar"],
        "recovery_hint": result["recovery_hint"],
        "data": {},
    }


async def test_get_leave_balance_unsupported_country(hris: InMemoryHRISAdapter) -> None:
    hris.seed_employee(
        Employee(
            employee_id="emp-2",
            full_name="No Policy",
            country="Atlantis",
            employment_start_date=date(2020, 1, 1),
            status="active",
        )
    )

    result = await get_leave_balance("emp-2", "annual", hris=hris, as_of=AS_OF)

    assert result["ok"] is False
    assert result["code"] == "COUNTRY_NOT_SUPPORTED"


async def test_get_leave_balance_unsupported_leave_type(hris: InMemoryHRISAdapter) -> None:
    result = await get_leave_balance("emp-1", "sick", hris=hris, as_of=AS_OF)

    assert result["ok"] is False
    assert result["code"] == "LEAVE_TYPE_NOT_SUPPORTED"


async def test_preview_leave_request_shape(hris: InMemoryHRISAdapter) -> None:
    await _seed_approved_days(hris, 3)
    settings = make_settings()

    result = await preview_leave_request(
        "emp-1",
        "annual",
        date(2026, 6, 1),
        date(2026, 6, 5),
        hris=hris,
        settings=settings,
        as_of=AS_OF,
        now=NOW,
    )

    assert result["ok"] is True
    assert isinstance(result["preview_token"], str) and "." in result["preview_token"]
    assert result["token_expires_at"] == "2026-06-01T09:15:00+00:00"
    data = result["data"]
    assert data["working_days"] == 4
    assert data["entitlement_days"] == 30
    assert data["taken_days"] == 3
    assert data["balance_before"] == 27
    assert data["balance_after"] == 23
    assert data["approver"] == {"employee_id": "mgr-1", "full_name": "Manager One"}
    assert "Manager One" in result["message_en"]


async def test_preview_leave_request_rejects_inverted_dates(hris: InMemoryHRISAdapter) -> None:
    result = await preview_leave_request(
        "emp-1",
        "annual",
        date(2026, 6, 5),
        date(2026, 6, 1),
        hris=hris,
        settings=make_settings(),
        as_of=AS_OF,
        now=NOW,
    )

    assert result["ok"] is False
    assert result["code"] == "INVALID_DATE_RANGE"


async def test_preview_leave_request_no_manager_found() -> None:
    hris = InMemoryHRISAdapter()
    hris.seed_employee(
        Employee(
            employee_id="emp-1",
            full_name="Sara Ahmed",
            country="KSA",
            employment_start_date=date(2020, 1, 1),
            status="active",
            manager_id=None,
        )
    )

    result = await preview_leave_request(
        "emp-1",
        "annual",
        date(2026, 6, 1),
        date(2026, 6, 5),
        hris=hris,
        settings=make_settings(),
        as_of=AS_OF,
        now=NOW,
    )

    assert result["ok"] is False
    assert result["code"] == "APPROVER_NOT_FOUND"


async def test_verify_preview_for_submission_happy_path(
    hris: InMemoryHRISAdapter, nonce_store: NonceStore
) -> None:
    await _seed_approved_days(hris, 3)
    settings = make_settings()
    preview = await preview_leave_request(
        "emp-1",
        "annual",
        date(2026, 6, 1),
        date(2026, 6, 5),
        hris=hris,
        settings=settings,
        as_of=AS_OF,
        now=NOW,
    )

    payload = await verify_preview_for_submission(
        preview["preview_token"],
        hris=hris,
        settings=settings,
        nonce_store=nonce_store,
        as_of=AS_OF,
        now=NOW,
    )

    assert payload["employee_id"] == "emp-1"
    assert payload["balance_before"] == 27


async def test_verify_preview_for_submission_rejects_replay(
    hris: InMemoryHRISAdapter, nonce_store: NonceStore
) -> None:
    settings = make_settings()
    preview = await preview_leave_request(
        "emp-1",
        "annual",
        date(2026, 6, 1),
        date(2026, 6, 5),
        hris=hris,
        settings=settings,
        as_of=AS_OF,
        now=NOW,
    )

    await verify_preview_for_submission(
        preview["preview_token"], hris=hris, settings=settings, nonce_store=nonce_store,
        as_of=AS_OF, now=NOW,
    )

    result = await verify_preview_for_submission(
        preview["preview_token"], hris=hris, settings=settings, nonce_store=nonce_store,
        as_of=AS_OF, now=NOW,
    )

    assert result["ok"] is False
    assert result["code"] == "PREVIEW_ALREADY_USED"


async def test_verify_preview_for_submission_rejects_an_expired_token(
    hris: InMemoryHRISAdapter, nonce_store: NonceStore
) -> None:
    settings = make_settings()
    preview = await preview_leave_request(
        "emp-1",
        "annual",
        date(2026, 6, 1),
        date(2026, 6, 5),
        hris=hris,
        settings=settings,
        as_of=AS_OF,
        now=NOW,
    )

    result = await verify_preview_for_submission(
        preview["preview_token"],
        hris=hris,
        settings=settings,
        nonce_store=nonce_store,
        as_of=AS_OF,
        now=NOW.replace(hour=9, minute=16),
    )

    assert result["ok"] is False
    assert result["code"] == "PREVIEW_EXPIRED"


async def test_verify_preview_for_submission_detects_balance_drift(
    hris: InMemoryHRISAdapter, nonce_store: NonceStore
) -> None:
    # The scenario from the spec: preview shows a balance, then another
    # request gets approved in the interim, changing days taken before
    # submit runs. The token proves what was shown, not that it still
    # holds -- submit must recheck and refuse rather than trust it.
    settings = make_settings()
    preview = await preview_leave_request(
        "emp-1",
        "annual",
        date(2026, 6, 1),
        date(2026, 6, 5),
        hris=hris,
        settings=settings,
        as_of=AS_OF,
        now=NOW,
    )

    await _seed_approved_days(hris, 3)  # drift happens after preview, before submit

    result = await verify_preview_for_submission(
        preview["preview_token"],
        hris=hris,
        settings=settings,
        nonce_store=nonce_store,
        as_of=AS_OF,
        now=NOW,
    )

    assert result["ok"] is False
    assert result["code"] == "BALANCE_CHANGED"


async def test_verify_preview_for_submission_detects_a_changed_approver(
    hris: InMemoryHRISAdapter, nonce_store: NonceStore
) -> None:
    settings = make_settings()
    preview = await preview_leave_request(
        "emp-1",
        "annual",
        date(2026, 6, 1),
        date(2026, 6, 5),
        hris=hris,
        settings=settings,
        as_of=AS_OF,
        now=NOW,
    )

    hris.seed_employee(
        Employee(
            employee_id="mgr-2",
            full_name="Manager Two",
            country="KSA",
            employment_start_date=date(2015, 1, 1),
            status="active",
        )
    )
    reassigned = Employee(
        employee_id="emp-1",
        full_name="Sara Ahmed",
        country="KSA",
        employment_start_date=date(2020, 1, 1),
        status="active",
        manager_id="mgr-2",
    )
    hris.seed_employee(reassigned)

    result = await verify_preview_for_submission(
        preview["preview_token"],
        hris=hris,
        settings=settings,
        nonce_store=nonce_store,
        as_of=AS_OF,
        now=NOW,
    )

    assert result["ok"] is False
    assert result["code"] == "BALANCE_CHANGED"


async def test_verify_preview_for_submission_rejects_a_tampered_signature_generically(
    hris: InMemoryHRISAdapter, nonce_store: NonceStore
) -> None:
    settings = make_settings()
    preview = await preview_leave_request(
        "emp-1",
        "annual",
        date(2026, 6, 1),
        date(2026, 6, 5),
        hris=hris,
        settings=settings,
        as_of=AS_OF,
        now=NOW,
    )
    payload_b64, signature_b64 = preview["preview_token"].split(".")
    tampered_signature = bytearray(base64.urlsafe_b64decode(signature_b64))
    tampered_signature[0] ^= 0xFF
    tampered_token = (
        payload_b64 + "." + base64.urlsafe_b64encode(bytes(tampered_signature)).decode("ascii")
    )

    result = await verify_preview_for_submission(
        tampered_token,
        hris=hris,
        settings=settings,
        nonce_store=nonce_store,
        as_of=AS_OF,
        now=NOW,
    )

    # Generic on purpose: the response must not say *why* it's invalid
    # (signature vs malformed vs which field), only that it is.
    assert result == {
        "ok": False,
        "code": "PREVIEW_INVALID",
        "message_en": "This preview token isn't valid.",
        "message_ar": "رمز المعاينة هذا غير صالح.",
        "recovery_hint": "Call preview_leave_request again to get a valid token.",
        "data": {},
    }


async def test_tampered_signature_is_logged_as_a_security_event(
    hris: InMemoryHRISAdapter, nonce_store: NonceStore, caplog: pytest.LogCaptureFixture
) -> None:
    settings = make_settings()
    preview = await preview_leave_request(
        "emp-1",
        "annual",
        date(2026, 6, 1),
        date(2026, 6, 5),
        hris=hris,
        settings=settings,
        as_of=AS_OF,
        now=NOW,
    )
    payload_b64, signature_b64 = preview["preview_token"].split(".")
    tampered_signature = bytearray(base64.urlsafe_b64decode(signature_b64))
    tampered_signature[0] ^= 0xFF
    tampered_token = (
        payload_b64 + "." + base64.urlsafe_b64encode(bytes(tampered_signature)).decode("ascii")
    )

    with caplog.at_level("WARNING", logger="app.security"):
        await verify_preview_for_submission(
            tampered_token,
            hris=hris,
            settings=settings,
            nonce_store=nonce_store,
            as_of=AS_OF,
            now=NOW,
        )

    assert any("app.security" == r.name and "signature" in r.message for r in caplog.records)
