import httpx

from app.config import Settings
from app.core import db
from app.core.idempotency import IdempotencyStore, NonceStore
from app.integrations.bamboohr.adapter import BambooHRAdapter
from app.integrations.bamboohr.client import BambooHRClient
from app.integrations.bamboohr.memory import InMemoryHRISAdapter
from app.integrations.ports import HRISPort

# Keyed on (driver, subdomain), not the Settings object itself -- Settings
# is a pydantic model without frozen=True, so it isn't hashable and can't
# go through lru_cache directly. Keying on the two fields that actually
# determine adapter identity gets the same singleton-per-config effect.
_hris_port_cache: dict[tuple[str, str | None], HRISPort] = {}
_nonce_store: NonceStore | None = None
_idempotency_store: IdempotencyStore | None = None


def get_hris_port(settings: Settings) -> HRISPort:
    cache_key = (settings.hris_driver, settings.bamboohr_subdomain)
    cached = _hris_port_cache.get(cache_key)
    if cached is not None:
        return cached

    port = _build_hris_port(settings)
    _hris_port_cache[cache_key] = port
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
