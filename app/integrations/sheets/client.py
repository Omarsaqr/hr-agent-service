import time
from typing import Any
from urllib.parse import quote

import httpx
from google.auth import jwt as google_jwt
from google.auth.crypt import RSASigner

from app.integrations.retry import request_with_retry

_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
_ASSERTION_TTL_SECONDS = 3600
# Refresh a bit before Google's own expiry, not exactly at it -- a request
# that starts an instant before the true expiry shouldn't race the clock.
_TOKEN_REFRESH_MARGIN_SECONDS = 60


class GoogleSheetsClient:
    """Talks the Sheets API v4 wire format only -- no domain types cross
    this boundary. Authenticates as a service account via the OAuth2 JWT
    Bearer flow (RFC 7523): a self-signed assertion is exchanged for a
    short-lived access token, cached until shortly before it expires.

    Deliberately not google-api-python-client or gspread -- both pull in
    a full client SDK for what is, underneath, two REST calls. google-auth
    alone (already a dependency of both of those, so nothing bigger is
    avoided by skipping it) covers the RSA-SHA256 JWT signing, which is
    the one piece of this that would be a mistake to hand-roll. Everything
    else goes through the same httpx + request_with_retry path as every
    other vendor integration here.
    """

    def __init__(
        self,
        spreadsheet_id: str,
        service_account_info: dict[str, Any],
        http_client: httpx.AsyncClient,
    ) -> None:
        self._spreadsheet_id = spreadsheet_id
        self._http = http_client
        self._client_email: str = service_account_info["client_email"]
        self._token_uri: str = service_account_info["token_uri"]
        self._signer = RSASigner.from_service_account_info(  # type: ignore[no-untyped-call]
            service_account_info
        )
        self._access_token: str | None = None
        self._access_token_expires_at: float = 0.0

    async def get_values(self, a1_range: str) -> list[list[str]]:
        token = await self._get_access_token()
        response = await request_with_retry(
            lambda: self._http.get(
                f"{self._base_url()}/values/{quote(a1_range, safe='')}",
                headers={"Authorization": f"Bearer {token}"},
            ),
            idempotent=True,
            service_name="Google Sheets",
        )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        # Sheets omits the "values" key entirely for an empty range,
        # rather than returning an empty list -- .get, not [].
        return body.get("values", [])  # type: ignore[no-any-return]

    async def append_values(self, a1_range: str, rows: list[list[str]]) -> None:
        token = await self._get_access_token()
        response = await request_with_retry(
            lambda: self._http.post(
                f"{self._base_url()}/values/{quote(a1_range, safe='')}:append",
                params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
                headers={"Authorization": f"Bearer {token}"},
                json={"values": rows},
            ),
            idempotent=False,
            service_name="Google Sheets",
        )
        response.raise_for_status()

    def _base_url(self) -> str:
        return f"https://sheets.googleapis.com/v4/spreadsheets/{self._spreadsheet_id}"

    async def _get_access_token(self) -> str:
        now = time.monotonic()
        if self._access_token is not None and now < self._access_token_expires_at:
            return self._access_token

        issued_at = int(time.time())
        signed_jwt: bytes = google_jwt.encode(  # type: ignore[no-untyped-call]
            self._signer,
            {
                "iss": self._client_email,
                "scope": _SCOPE,
                "aud": self._token_uri,
                "iat": issued_at,
                "exp": issued_at + _ASSERTION_TTL_SECONDS,
            },
        )
        assertion = signed_jwt.decode("ascii")

        response = await request_with_retry(
            lambda: self._http.post(
                self._token_uri,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
            ),
            idempotent=True,
            service_name="Google OAuth",
        )
        response.raise_for_status()
        body = response.json()
        self._access_token = body["access_token"]
        self._access_token_expires_at = now + body["expires_in"] - _TOKEN_REFRESH_MARGIN_SECONDS
        return self._access_token
