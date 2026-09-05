from datetime import date

from app.domain.models import CheckinRecord


class InMemorySheetAdapter:
    """List-backed DashboardPort implementation for tests and the offline demo."""

    def __init__(self) -> None:
        self._checkins: list[CheckinRecord] = []

    async def append_checkin(self, checkin: CheckinRecord) -> None:
        self._checkins.append(checkin)

    async def get_checkins(
        self, employee_ids: list[str], start: date, end: date
    ) -> list[CheckinRecord]:
        latest: dict[tuple[str, date], CheckinRecord] = {}
        for checkin in self._checkins:
            if checkin.employee_id not in employee_ids:
                continue
            if not (start <= checkin.checkin_date <= end):
                continue
            key = (checkin.employee_id, checkin.checkin_date)
            current = latest.get(key)
            if current is None or checkin.submitted_at > current.submitted_at:
                latest[key] = checkin
        return list(latest.values())
