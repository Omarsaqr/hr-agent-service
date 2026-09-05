from app.integrations.bamboohr.memory import InMemoryHRISAdapter
from app.integrations.ports import DashboardPort, HRISPort
from app.integrations.sheets.memory import InMemorySheetAdapter


def test_in_memory_hris_adapter_satisfies_hris_port() -> None:
    assert isinstance(InMemoryHRISAdapter(), HRISPort)


def test_in_memory_sheet_adapter_satisfies_dashboard_port() -> None:
    assert isinstance(InMemorySheetAdapter(), DashboardPort)
