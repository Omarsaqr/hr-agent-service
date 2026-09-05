from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.integrations.bamboohr.memory import InMemoryHRISAdapter
from app.integrations.sheets.memory import InMemorySheetAdapter


@dataclass
class E2EContext:
    client: TestClient
    hris: InMemoryHRISAdapter
    dashboard: InMemorySheetAdapter
