import json

import httpx

from app.config import Settings
from app.core import db
from app.core.audit import AuditLog
from app.core.idempotency import IdempotencyStore, NonceStore
from app.integrations.bamboohr.adapter import BambooHRAdapter
from app.integrations.bamboohr.client import BambooHRClient
from app.integrations.bamboohr.memory import InMemoryHRISAdapter
from app.integrations.ports import DashboardPort, HRISPort
from app.integrations.sheets.adapter import GoogleSheetsAdapter
from app.integrations.sheets.client import GoogleSheetsClient
from app.integrations.sheets.memory import InMemorySheetAdapter

# Keyed on (driver, subdomain), not the Settings object itself -- Settings
# is a pydantic model without frozen=True, so it isn't hashable and can't
# go through lru_cache directly. Keying on the two fields that actually
# determine adapter identity gets the same singleton-per-config effect.
_hris_port_cache: dict[tuple[str, str | None], HRISPort] = {}
_dashboard_port_cache: dict[tuple[str, str | None], DashboardPort] = {}
_nonce_store: NonceStore | None = None
_idempotency_store: IdempotencyStore | None = None
_audit_log: AuditLog | None = None


def get_hris_port(settings: Settings) -> HRISPort:
    cache_key = (settings.hris_driver, settings.bamboohr_subdomain)
    cached = _hris_port_cache.get(cache_key)
    if cached is not None:
        return cached

    port = _build_hris_port(settings)
    _hris_port_cache[cache_key] = port
    return port


def get_dashboard_port(settings: Settings) -> DashboardPort:
    cache_key = (settings.dashboard_driver, settings.google_sheets_spreadsheet_id)
    cached = _dashboard_port_cache.get(cache_key)
    if cached is not None:
        return cached

    port = _build_dashboard_port(settings)
    _dashboard_port_cache[cache_key] = port
    return port


def get_nonce_store() -> NonceStore:
    # A single process-lifetime connection, not one per call: sqlite3
    # connections aren't free, and the nonce table needs to see every
    # consumption to actually enforce single use.
    global _nonce_store
    if _nonce_store is None:
        _nonce_store = NonceStore(db.connect())
    return _nonce_store


def get_idempotency_store() -> IdempotencyStore:
    global _idempotency_store
    if _idempotency_store is None:
        _idempotency_store = IdempotencyStore(db.connect())
    return _idempotency_store


def get_audit_log() -> AuditLog:
    global _audit_log
    if _audit_log is None:
        _audit_log = AuditLog(db.connect())
    return _audit_log


def _build_hris_port(settings: Settings) -> HRISPort:
    if settings.hris_driver == "memory":
        return InMemoryHRISAdapter()

    if settings.bamboohr_subdomain is None or settings.bamboohr_api_key is None:
        raise RuntimeError(
            "HRIS_DRIVER=bamboohr requires BAMBOOHR_SUBDOMAIN and BAMBOOHR_API_KEY"
        )
    client = BambooHRClient(
        settings.bamboohr_subdomain,
        settings.bamboohr_api_key.get_secret_value(),
        httpx.AsyncClient(),
    )
    return BambooHRAdapter(client)


def _build_dashboard_port(settings: Settings) -> DashboardPort:
    if settings.dashboard_driver == "memory":
        return InMemorySheetAdapter()

    if settings.google_sheets_credentials_path is None:
        raise RuntimeError("DASHBOARD_DRIVER=sheets requires GOOGLE_SHEETS_CREDENTIALS_PATH")
    if settings.google_sheets_spreadsheet_id is None:
        raise RuntimeError("DASHBOARD_DRIVER=sheets requires GOOGLE_SHEETS_SPREADSHEET_ID")

    # The service-account key file's content is the secret, not anything
    # that passes through Settings -- read here, at the one place that
    # needs it, and never logged or echoed.
    with open(settings.google_sheets_credentials_path, encoding="utf-8") as f:
        service_account_info = json.load(f)
    client = GoogleSheetsClient(
        settings.google_sheets_spreadsheet_id, service_account_info, httpx.AsyncClient()
    )
    return GoogleSheetsAdapter(client, settings.google_sheets_sheet_name)
