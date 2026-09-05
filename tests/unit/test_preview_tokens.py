import base64
import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from app.core.idempotency import NonceStore
from app.core.preview_tokens import (
    PreviewTokenExpiredError,
    PreviewTokenFields,
    PreviewTokenInvalidError,
    PreviewTokenReusedError,
    issue,
    verify,
    verify_and_consume,
)

SECRET = "test-secret"
NOW = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)


def make_fields(**overrides: object) -> PreviewTokenFields:
    defaults: dict[str, object] = {
        "employee_id": "142",
        "leave_type": "annual",
        "country": "KSA",
        "start_date": "2026-06-01",
        "end_date": "2026-06-05",
        "working_days": 5.0,
        "balance_before": 18.0,
        "balance_after": 13.0,
        "approver_id": "88",
    }
    defaults.update(overrides)
    return PreviewTokenFields(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def nonce_store() -> NonceStore:
    return NonceStore(sqlite3.connect(":memory:"))


def test_round_trip_returns_the_signed_fields() -> None:
    token = issue(make_fields(), secret=SECRET, now=NOW)

    payload = verify(token, secret=SECRET, now=NOW)

    assert payload["employee_id"] == "142"
    assert payload["country"] == "KSA"
    assert payload["approver_id"] == "88"
    assert payload["issued_at"] == NOW.isoformat()
    assert "nonce" in payload


def test_expired_token_is_rejected() -> None:
    token = issue(make_fields(), secret=SECRET, now=NOW)

    with pytest.raises(PreviewTokenExpiredError):
        verify(token, secret=SECRET, now=NOW + timedelta(minutes=15, seconds=1))


def test_token_still_valid_one_second_before_ttl() -> None:
    token = issue(make_fields(), secret=SECRET, now=NOW)

    # Boundary case, named: 15 minutes minus a second must still pass.
    payload = verify(token, secret=SECRET, now=NOW + timedelta(minutes=14, seconds=59))

    assert payload["employee_id"] == "142"


def test_expiry_is_computed_only_from_the_signed_issued_at() -> None:
    # There is no code path for an external "claimed expiry" to enter
    # verify() at all -- it takes only the token string. This pins that
    # down concretely: even simulating an attacker who could make some
    # *other* system believe the token is valid for another hour, the
    # real check (decoded from inside the signed payload) still rejects
    # it once the actual 15-minute TTL has passed.
    token = issue(make_fields(), secret=SECRET, now=NOW)
    attacker_claimed_expiry = NOW + timedelta(hours=1)
    check_time = NOW + timedelta(minutes=20)
    assert check_time < attacker_claimed_expiry  # the fake claim would say "still valid"

    with pytest.raises(PreviewTokenExpiredError):
        verify(token, secret=SECRET, now=check_time)


def test_flipped_byte_in_signature_is_rejected() -> None:
    token = issue(make_fields(), secret=SECRET, now=NOW)
    payload_b64, signature_b64 = token.split(".")
    signature = bytearray(base64.urlsafe_b64decode(signature_b64))
    signature[0] ^= 0xFF
    tampered = payload_b64 + "." + base64.urlsafe_b64encode(bytes(signature)).decode("ascii")

    with pytest.raises(PreviewTokenInvalidError):
        verify(tampered, secret=SECRET, now=NOW)


def test_flipped_byte_in_payload_is_rejected() -> None:
    token = issue(make_fields(), secret=SECRET, now=NOW)
    payload_b64, signature_b64 = token.split(".")
    payload_bytes = bytearray(base64.urlsafe_b64decode(payload_b64))
    payload_bytes[0] ^= 0xFF
    tampered = base64.urlsafe_b64encode(bytes(payload_bytes)).decode("ascii") + "." + signature_b64

    with pytest.raises(PreviewTokenInvalidError):
        verify(tampered, secret=SECRET, now=NOW)


def test_token_signed_with_a_different_secret_is_rejected() -> None:
    token = issue(make_fields(), secret="secret-a", now=NOW)

    with pytest.raises(PreviewTokenInvalidError):
        verify(token, secret="secret-b", now=NOW)


def test_malformed_token_is_rejected() -> None:
    with pytest.raises(PreviewTokenInvalidError):
        verify("not-a-token-at-all", secret=SECRET, now=NOW)


def test_malformed_json_payload_is_rejected() -> None:
    garbage_payload = base64.urlsafe_b64encode(b"not json").decode("ascii")
    fake_signature = base64.urlsafe_b64encode(b"whatever").decode("ascii")

    with pytest.raises(PreviewTokenInvalidError):
        verify(f"{garbage_payload}.{fake_signature}", secret=SECRET, now=NOW)


def test_invalid_token_errors_carry_no_field_specific_detail_in_their_type() -> None:
    # Bad signature and a malformed payload must be indistinguishable to
    # anything that only catches PreviewTokenInvalidError -- both raise
    # the exact same exception type, so a caller cannot branch on cause
    # even if it tried to.
    token = issue(make_fields(), secret=SECRET, now=NOW)
    payload_b64, signature_b64 = token.split(".")
    bad_signature = bytearray(base64.urlsafe_b64decode(signature_b64))
    bad_signature[0] ^= 0xFF
    tampered_signature = payload_b64 + "." + base64.urlsafe_b64encode(bytes(bad_signature)).decode(
        "ascii"
    )

    errors: list[Exception] = []
    for bad_token in ("garbage", tampered_signature):
        try:
            verify(bad_token, secret=SECRET, now=NOW)
        except PreviewTokenInvalidError as exc:
            errors.append(exc)

    assert len(errors) == 2
    assert {type(e) for e in errors} == {PreviewTokenInvalidError}


def test_nonce_store_rejects_a_second_consumption(nonce_store: NonceStore) -> None:
    assert nonce_store.consume("nonce-1", NOW) is True
    assert nonce_store.consume("nonce-1", NOW) is False


def test_nonce_store_allows_different_nonces(nonce_store: NonceStore) -> None:
    assert nonce_store.consume("nonce-1", NOW) is True
    assert nonce_store.consume("nonce-2", NOW) is True


def test_verify_and_consume_rejects_replay_of_the_same_token(nonce_store: NonceStore) -> None:
    token = issue(make_fields(), secret=SECRET, now=NOW)

    first = verify_and_consume(token, secret=SECRET, now=NOW, nonce_store=nonce_store)
    assert first["employee_id"] == "142"

    with pytest.raises(PreviewTokenReusedError):
        verify_and_consume(token, secret=SECRET, now=NOW, nonce_store=nonce_store)


def test_verify_and_consume_allows_two_different_tokens(nonce_store: NonceStore) -> None:
    token_a = issue(make_fields(), secret=SECRET, now=NOW)
    token_b = issue(make_fields(), secret=SECRET, now=NOW)

    verify_and_consume(token_a, secret=SECRET, now=NOW, nonce_store=nonce_store)
    verify_and_consume(token_b, secret=SECRET, now=NOW, nonce_store=nonce_store)  # does not raise


def test_signed_payload_round_trips_through_json_correctly() -> None:
    # Guards the canonical-json contract itself: sort_keys + compact
    # separators, so the same logical payload always signs identically.
    token = issue(make_fields(), secret=SECRET, now=NOW)
    payload_b64 = token.split(".")[0]
    raw = base64.urlsafe_b64decode(payload_b64)

    assert raw == json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":")).encode()
