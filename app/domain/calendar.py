import tomllib
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

_TABLE_PATH = Path(__file__).parent / "calendar.toml"


@dataclass(frozen=True, slots=True)
class PublicHoliday:
    day: date
    name: str


@dataclass(frozen=True, slots=True)
class CountryCalendar:
    weekend_weekdays: tuple[int, ...]
    holidays: tuple[PublicHoliday, ...]


def _load_calendar(raw: dict[str, Any]) -> CountryCalendar:
    holidays = tuple(
        PublicHoliday(day=entry["date"], name=entry["name"]) for entry in raw.get("holidays", [])
    )
    return CountryCalendar(weekend_weekdays=tuple(raw["weekend_weekdays"]), holidays=holidays)


def _load_calendars() -> dict[str, CountryCalendar]:
    with _TABLE_PATH.open("rb") as f:
        raw = tomllib.load(f)
    return {code: _load_calendar(entry) for code, entry in raw.items()}


COUNTRY_CALENDARS: dict[str, CountryCalendar] = _load_calendars()


def is_working_day(calendar: CountryCalendar, day: date) -> bool:
    if day.weekday() in calendar.weekend_weekdays:
        return False
    return all(holiday.day != day for holiday in calendar.holidays)


def working_days_between(calendar: CountryCalendar, start: date, end: date) -> int:
    """Inclusive count of working days in [start, end]."""
    if end < start:
        return 0

    holiday_dates = {holiday.day for holiday in calendar.holidays}
    one_day = timedelta(days=1)
    count = 0
    current = start
    while current <= end:
        if current.weekday() not in calendar.weekend_weekdays and current not in holiday_dates:
            count += 1
        current += one_day
    return count
