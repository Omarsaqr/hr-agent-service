import pytest
from fastapi.testclient import TestClient

import app.deps as deps_module
from app.integrations.bamboohr.memory import InMemoryHRISAdapter
from app.integrations.llm.mock import MockLLMAdapter
from app.integrations.sheets.memory import InMemorySheetAdapter
from app.main import app
from tests.e2e.support import E2EContext


@pytest.fixture
def e2e(monkeypatch: pytest.MonkeyPatch) -> E2EContext:
    """A TestClient wired to fresh, test-owned in-memory adapters.

    The running app resolves its HRIS/Dashboard/LLM ports through
    deps.get_hris_port/get_dashboard_port/get_llm_port, which cache by
    settings value, not by test identity -- so a fresh
    InMemoryHRISAdapter() in this test's own scope would never actually
    be seen by the app unless it's the one sitting in deps.py's cache
    under the app's real settings key. monkeypatch.setitem swaps it in
    and restores whatever was there afterward, giving each test a
    clean, isolated adapter pair without another e2e test (or a future
    user of these same settings) ever seeing seeded data left behind.

    The LLM port needs the same treatment for a reason the other two
    don't: these tests assert on MockLLMAdapter's specific deterministic
    replies, so they need mock regardless of what LLM_DRIVER the real
    .env happens to be set to right now (e.g. gemini, for someone trying
    a live key against the running dev server) -- otherwise they either
    fail against a real model's different wording or, worse, silently
    spend a real API call per test run. Caught exactly this way: these
    tests broke the moment .env's LLM_DRIVER changed, because nothing
    here pinned it. See docs/ROADMAP.md.
    """
    settings = app.state.settings
    hris = InMemoryHRISAdapter()
    dashboard = InMemorySheetAdapter()

    monkeypatch.setitem(
        deps_module._hris_port_cache,
        (settings.hris_driver, settings.bamboohr_subdomain),
        hris,
    )
    monkeypatch.setitem(
        deps_module._dashboard_port_cache,
        (settings.dashboard_driver, settings.google_sheets_spreadsheet_id),
        dashboard,
    )
    monkeypatch.setitem(deps_module._llm_port_cache, settings.llm_driver, MockLLMAdapter())

    return E2EContext(client=TestClient(app), hris=hris, dashboard=dashboard)
