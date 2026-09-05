import sqlite3

import pytest

import app.deps as deps_module
from app.config import Settings
from app.core.idempotency import IdempotencyStore, NonceStore
from app.deps import (
    _dashboard_port_cache,
    _hris_port_cache,
    _llm_port_cache,
    get_dashboard_port,
    get_gap_log,
    get_hris_port,
    get_idempotency_store,
    get_knowledge_store,
    get_llm_port,
    get_nonce_store,
)
from app.integrations.bamboohr.memory import InMemoryHRISAdapter
from app.integrations.llm.mock import MockLLMAdapter
from app.integrations.sheets.memory import InMemorySheetAdapter
from app.knowledge.gaps import GapLog
from app.knowledge.store import KnowledgeStore


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    # The cache is deliberately module-level (one adapter per config for
    # the app's lifetime) -- tests need a clean slate each time or they'd
    # leak instances across cases.
    _hris_port_cache.clear()
    _dashboard_port_cache.clear()
    _llm_port_cache.clear()
    deps_module._nonce_store = None
    deps_module._idempotency_store = None
    deps_module._knowledge_store = None
    deps_module._gap_log = None


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


def test_memory_dashboard_driver_returns_an_in_memory_adapter() -> None:
    port = get_dashboard_port(make_settings(dashboard_driver="memory"))

    assert isinstance(port, InMemorySheetAdapter)


def test_same_dashboard_settings_key_returns_the_same_instance() -> None:
    settings = make_settings(dashboard_driver="memory")

    assert get_dashboard_port(settings) is get_dashboard_port(settings)


def test_sheets_driver_without_credentials_path_raises() -> None:
    settings = make_settings(
        dashboard_driver="sheets", google_sheets_spreadsheet_id="some-id"
    )

    with pytest.raises(RuntimeError):
        get_dashboard_port(settings)


def test_sheets_driver_without_spreadsheet_id_raises() -> None:
    settings = make_settings(
        dashboard_driver="sheets", google_sheets_credentials_path="/tmp/fake.json"
    )

    with pytest.raises(RuntimeError):
        get_dashboard_port(settings)


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


def test_get_knowledge_store_returns_the_same_instance_every_call() -> None:
    store = get_knowledge_store()

    assert isinstance(store, KnowledgeStore)
    assert get_knowledge_store() is store


def test_get_gap_log_returns_the_same_instance_every_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.db.connect", lambda: sqlite3.connect(":memory:"))

    log = get_gap_log()

    assert isinstance(log, GapLog)
    assert get_gap_log() is log


def test_mock_llm_driver_returns_a_mock_adapter() -> None:
    port = get_llm_port(make_settings(llm_driver="mock"))

    assert isinstance(port, MockLLMAdapter)


def test_same_llm_driver_returns_the_same_instance() -> None:
    settings = make_settings(llm_driver="mock")

    assert get_llm_port(settings) is get_llm_port(settings)


def test_gemini_driver_without_api_key_raises() -> None:
    settings = make_settings(llm_driver="gemini")

    with pytest.raises(RuntimeError):
        get_llm_port(settings)
