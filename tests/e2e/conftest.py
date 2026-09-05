import pytest
from fastapi.testclient import TestClient

import app.deps as deps_module
from app.integrations.bamboohr.memory import InMemoryHRISAdapter
from app.integrations.sheets.memory import InMemorySheetAdapter
from app.main import app
from tests.e2e.support import E2EContext


@pytest.fixture
def e2e(monkeypatch: pytest.MonkeyPatch) -> E2EContext:
    """A TestClient wired to fresh, test-owned in-memory adapters.

    The running app resolves its HRIS/Dashboard ports through
    deps.get_hris_port/get_dashboard_port, which cache by settings
    value, not by test identity -- so a fresh InMemoryHRISAdapter() in
    this test's own scope would never actually be seen by the app
    unless it's the one sitting in deps.py's cache under the app's real
    settings key. monkeypatch.setitem swaps it in and restores whatever
    was there afterward, giving each test a clean, isolated adapter
    pair without another e2e test (or a future user of these same
    settings) ever seeing seeded data left behind.
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

    return E2EContext(client=TestClient(app), hris=hris, dashboard=dashboard)
