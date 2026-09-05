import json

import httpx
from google import genai

from app.agent.sessions import SessionStore
from app.config import Settings
from app.core import db
from app.core.audit import AuditLog
from app.core.idempotency import IdempotencyStore, NonceStore
from app.integrations.bamboohr.adapter import BambooHRAdapter
from app.integrations.bamboohr.client import BambooHRClient
from app.integrations.bamboohr.memory import InMemoryHRISAdapter
from app.integrations.llm.gemini import GeminiLLMAdapter
from app.integrations.llm.mock import MockLLMAdapter
from app.integrations.llm.ports import LLMPort
from app.integrations.ports import DashboardPort, HRISPort
from app.integrations.sheets.adapter import GoogleSheetsAdapter
from app.integrations.sheets.client import GoogleSheetsClient
from app.integrations.sheets.memory import InMemorySheetAdapter
from app.knowledge.gaps import GapLog
from app.knowledge.store import KnowledgeStore

# Keyed on (driver, subdomain), not the Settings object itself -- Settings
# is a pydantic model without frozen=True, so it isn't hashable and can't
# go through lru_cache directly. Keying on the two fields that actually
# determine adapter identity gets the same singleton-per-config effect.
_hris_port_cache: dict[tuple[str, str | None], HRISPort] = {}
_dashboard_port_cache: dict[tuple[str, str | None], DashboardPort] = {}
_llm_port_cache: dict[str, LLMPort] = {}
_nonce_store: NonceStore | None = None
_idempotency_store: IdempotencyStore | None = None
_audit_log: AuditLog | None = None
_knowledge_store: KnowledgeStore | None = None
_gap_log: GapLog | None = None
_session_store: SessionStore | None = None


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


def get_knowledge_store() -> KnowledgeStore:
    # Loads and BM25-indexes the corpus once per process -- cheap at
    # ~56 chunks, but no reason to redo it per request either.
    global _knowledge_store
    if _knowledge_store is None:
        _knowledge_store = KnowledgeStore()
    return _knowledge_store


def get_gap_log() -> GapLog:
    global _gap_log
    if _gap_log is None:
        _gap_log = GapLog(db.connect())
    return _gap_log


def get_session_store() -> SessionStore:
    global _session_store
    if _session_store is None:
        _session_store = SessionStore()
    return _session_store


def get_llm_port(settings: Settings) -> LLMPort:
    cache_key = settings.llm_driver
    cached = _llm_port_cache.get(cache_key)
    if cached is not None:
        return cached

    port = _build_llm_port(settings)
    _llm_port_cache[cache_key] = port
    return port


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


def _build_llm_port(settings: Settings) -> LLMPort:
    if settings.llm_driver == "mock":
        return MockLLMAdapter()

    if settings.gemini_api_key is None:
        raise RuntimeError("LLM_DRIVER=gemini requires GEMINI_API_KEY")
    client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())
    return GeminiLLMAdapter(client, settings.gemini_model)
