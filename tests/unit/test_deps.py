import sqlite3

import pytest

import app.deps as deps_module
from app.config import Settings
from app.core.idempotency import IdempotencyStore, NonceStore
from app.deps import _hris_port_cache, get_hris_port, get_idempotency_store, get_nonce_store
from app.integrations.bamboohr.memory import InMemoryHRISAdapter


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    # The cache is deliberately module-level (one adapter per config for
    # the app's lifetime) -- tests need a clean slate each time or they'd
    # leak instances across cases.
    _hris_port_cache.clear()
    deps_module._nonce_store = None
    deps_module._idempotency_store = None


def make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "_env_file": None,
        "environment": "test",
        "preview_token_secret": "test-secret",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_memory_driver_returns_an_in_memory_adapter() -> None:
    port = get_hris_port(make_settings(hris_driver="memory"))

    assert isinstance(port, InMemoryHRISAdapter)


def test_same_settings_key_returns_the_same_instance() -> None:
    settings = make_settings(hris_driver="memory")

    assert get_hris_port(settings) is get_hris_port(settings)


def test_bamboohr_driver_without_credentials_raises() -> None:
    settings = make_settings(hris_driver="bamboohr")

    with pytest.raises(RuntimeError):
        get_hris_port(settings)


def test_get_nonce_store_returns_the_same_instance_every_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # In-memory, not the real default path: this only checks the
    # singleton-caching behaviour, not that it writes to var/app.db.
    # Patched at its source module: deps.py does `from app.core import
    # db`, binding the same module object, so this is visible there too.
    monkeypatch.setattr("app.core.db.connect", lambda: sqlite3.connect(":memory:"))

    store = get_nonce_store()

    assert isinstance(store, NonceStore)
    assert get_nonce_store() is store


def test_get_idempotency_store_returns_the_same_instance_every_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.db.connect", lambda: sqlite3.connect(":memory:"))

    store = get_idempotency_store()

    assert isinstance(store, IdempotencyStore)
    assert get_idempotency_store() is store
