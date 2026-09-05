import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

_TABLE_PATH = Path(__file__).parent / "countries.toml"


@dataclass(frozen=True, slots=True)
class EntitlementTier:
    min_months: int
    annual_days: float | None = None
    monthly_accrual_days: float | None = None
    # Egypt: the 10-year tier is also reached at age 50, whichever is first.
    min_age_alternative: int | None = None


@dataclass(frozen=True, slots=True)
class SickLeaveTier:
    max_cumulative_days: int
    pay_percentage: float


@dataclass(frozen=True, slots=True)
class AnnualLeavePolicy:
    citation: str
    source_url: str
    last_reviewed: date
    tiers: tuple[EntitlementTier, ...]
    note: str | None = None


@dataclass(frozen=True, slots=True)
class SickLeavePolicy:
    citation: str
    source_url: str
    last_reviewed: date
    tiers: tuple[SickLeaveTier, ...]
    note: str | None = None


@dataclass(frozen=True, slots=True)
class CountryLeavePolicy:
    name: str
    annual_leave: AnnualLeavePolicy
    sick_leave: SickLeavePolicy | None = None


def _load_annual_leave(raw: dict[str, Any]) -> AnnualLeavePolicy:
    tiers = tuple(
        sorted(
            (
                EntitlementTier(
                    min_months=tier["min_months"],
                    annual_days=tier.get("annual_days"),
                    monthly_accrual_days=tier.get("monthly_accrual_days"),
                    min_age_alternative=tier.get("min_age_alternative"),
                )
                for tier in raw["tiers"]
            ),
            key=lambda tier: tier.min_months,
        )
    )
    return AnnualLeavePolicy(
        citation=raw["citation"],
        source_url=raw["source_url"],
        last_reviewed=raw["last_reviewed"],
        tiers=tiers,
        note=raw.get("note"),
    )


def _load_sick_leave(raw: dict[str, Any] | None) -> SickLeavePolicy | None:
    if raw is None:
        return None
    tiers = tuple(
        sorted(
            (
                SickLeaveTier(
                    max_cumulative_days=tier["max_cumulative_days"],
                    pay_percentage=tier["pay_percentage"],
                )
                for tier in raw["tiers"]
            ),
            key=lambda tier: tier.max_cumulative_days,
        )
    )
    return SickLeavePolicy(
        citation=raw["citation"],
        source_url=raw["source_url"],
        last_reviewed=raw["last_reviewed"],
        tiers=tiers,
        note=raw.get("note"),
    )


def _load_policies() -> dict[str, CountryLeavePolicy]:
    with _TABLE_PATH.open("rb") as f:
        raw = tomllib.load(f)

    return {
        code: CountryLeavePolicy(
            name=entry["name"],
            annual_leave=_load_annual_leave(entry["annual_leave"]),
            sick_leave=_load_sick_leave(entry.get("sick_leave")),
        )
        for code, entry in raw.items()
    }


COUNTRY_POLICIES: dict[str, CountryLeavePolicy] = _load_policies()
