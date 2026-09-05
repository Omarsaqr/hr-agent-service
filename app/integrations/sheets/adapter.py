from datetime import date, datetime

from app.domain.models import CheckinRecord
from app.integrations.sheets.client import GoogleSheetsClient

# Mirrors CheckinRecord's field order exactly -- the sheet's columns are
# a direct, 1:1 rendering of the domain record, not a reformatted view.
_EXPECTED_HEADERS = [
    "employee_id",
    "checkin_date",
    "accomplishments",
    "blockers",
    "rating",
    "submitted_by",
    "submitted_at",
    "idempotency_key",
]


class HeaderMismatchError(Exception):
    """The sheet's header row doesn't match the columns this adapter expects."""


class GoogleSheetsAdapter:
    """DashboardPort implementation. The only file besides client.py that
    knows the sheet's column layout -- everything it returns is a domain
    dataclass.
    """

    def __init__(self, client: GoogleSheetsClient, sheet_name: str = "checkins") -> None:
        self._client = client
        self._sheet_name = sheet_name
        self._headers_validated = False

    async def append_checkin(self, checkin: CheckinRecord) -> None:
        await self._ensure_headers_valid()
        row = [
            checkin.employee_id,
            checkin.checkin_date.isoformat(),
            checkin.accomplishments,
            checkin.blockers,
            str(checkin.rating),
            checkin.submitted_by,
            checkin.submitted_at.isoformat(),
            checkin.idempotency_key,
        ]
        await self._client.append_values(self._sheet_name, [row])

    async def get_checkins(
        self, employee_ids: list[str], start: date, end: date
    ) -> list[CheckinRecord]:
        await self._ensure_headers_valid()
        rows = await self._client.get_values(self._sheet_name)

        latest: dict[tuple[str, date], CheckinRecord] = {}
        for raw_row in rows[1:]:  # rows[0] is the header
            record = _row_to_checkin(raw_row)
            if record is None or record.employee_id not in employee_ids:
                continue
            if not (start <= record.checkin_date <= end):
                continue
            key = (record.employee_id, record.checkin_date)
            current = latest.get(key)
            if current is None or record.submitted_at > current.submitted_at:
                latest[key] = record
        return list(latest.values())

    async def _ensure_headers_valid(self) -> None:
        # Checked once per process lifetime, lazily on first real use --
        # not at construction, since validation needs an async call and
        # __init__ can't make one. Same lazy-validate-once shape as
        # BambooHRAdapter._get_validated_time_off_types.
        if self._headers_validated:
            return
        rows = await self._client.get_values(f"{self._sheet_name}!1:1")
        actual = rows[0] if rows else []
        if actual != _EXPECTED_HEADERS:
            raise HeaderMismatchError(
                f"sheet '{self._sheet_name}' header row {actual!r} does not match "
                f"the expected columns {_EXPECTED_HEADERS!r}"
            )
        self._headers_validated = True


def _row_to_checkin(raw_row: list[str]) -> CheckinRecord | None:
    # The Sheets API trims trailing empty cells from a row, not just
    # trailing empty rows from a range -- a row with a blank last column
    # comes back shorter than _EXPECTED_HEADERS. Padding before indexing
    # avoids an IndexError on a perfectly valid, common response shape.
    padded = raw_row + [""] * (len(_EXPECTED_HEADERS) - len(raw_row))
    if not padded[0]:
        return None
    return CheckinRecord(
        employee_id=padded[0],
        checkin_date=date.fromisoformat(padded[1]),
        accomplishments=padded[2],
        blockers=padded[3],
        rating=int(padded[4]),
        submitted_by=padded[5],
        submitted_at=datetime.fromisoformat(padded[6]),
        idempotency_key=padded[7],
    )
