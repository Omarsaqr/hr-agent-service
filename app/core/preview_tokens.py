import base64
import binascii
import hashlib
import hmac
import json
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from app.core.idempotency import NonceStore

TOKEN_TTL = timedelta(minutes=15)


class PreviewTokenExpiredError(Exception):
    """The signed issued_at is older than TOKEN_TTL."""


class PreviewTokenInvalidError(Exception):
    """Bad signature or malformed token. `reason` is for the security log
    only -- callers must never surface it in a tool response, or an
    attacker probing signatures could use the difference to learn which
    field broke.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class PreviewTokenReusedError(Exception):
    """The token's nonce was already consumed by an earlier submit."""


@dataclass(frozen=True, slots=True)
class PreviewTokenFields:
    employee_id: str
    leave_type: str
    country: str
    start_date: str
    end_date: str
    working_days: float
    balance_before: float
    balance_after: float
    approver_id: str


def issue(fields: PreviewTokenFields, *, secret: str, now: datetime) -> str:
    payload = {
        **asdict(fields),
        "issued_at": now.isoformat(),
        "nonce": secrets.token_hex(16),
    }
    payload_bytes = _canonical_json(payload)
    signature = _sign(payload_bytes, secret)
    return _b64(payload_bytes) + "." + _b64(signature)


def verify(token: str, *, secret: str, now: datetime) -> dict[str, Any]:
    """Signature and freshness only -- does not touch the nonce store.
    Raises PreviewTokenInvalidError (bad signature or malformed) or
    PreviewTokenExpiredError. Returns the decoded payload dict on success.
    """
    payload_bytes, signature = _decode_token(token)

    expected_signature = _sign(payload_bytes, secret)
    if not hmac.compare_digest(signature, expected_signature):
        raise PreviewTokenInvalidError("signature mismatch")

    payload = _decode_payload(payload_bytes)

    # Expiry is computed only from the signed issued_at. A caller may
    # separately display an unsigned "expires_at" for humans, but that
    # value is never read here -- it isn't part of what's signed, so an
    # attacker could edit it freely, and trusting it would make the TTL
    # meaningless rather than enforced.
    issued_at = datetime.fromisoformat(payload["issued_at"])
    if now - issued_at > TOKEN_TTL:
        raise PreviewTokenExpiredError("token expired")

    return payload


def verify_and_consume(
    token: str, *, secret: str, now: datetime, nonce_store: NonceStore
) -> dict[str, Any]:
    """verify() plus single-use enforcement. This is what submit calls."""
    payload = verify(token, secret=secret, now=now)
    if not nonce_store.consume(payload["nonce"], now):
        raise PreviewTokenReusedError("nonce already consumed")
    return payload


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sign(payload_bytes: bytes, secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _decode_token(token: str) -> tuple[bytes, bytes]:
    parts = token.split(".")
    if len(parts) != 2:
        raise PreviewTokenInvalidError("malformed: expected exactly one '.' separator")
    try:
        payload_bytes = base64.urlsafe_b64decode(parts[0])
        signature = base64.urlsafe_b64decode(parts[1])
    except (binascii.Error, ValueError) as exc:
        raise PreviewTokenInvalidError("malformed: invalid base64") from exc
    return payload_bytes, signature


def _decode_payload(payload_bytes: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(payload_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PreviewTokenInvalidError("malformed: invalid json") from exc
    if not isinstance(payload, dict) or "issued_at" not in payload or "nonce" not in payload:
        raise PreviewTokenInvalidError("malformed: missing required payload fields")
    return payload
