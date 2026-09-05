import tomllib
from pathlib import Path

_TABLE_PATH = Path(__file__).parent / "leave_type_mapping.toml"


class LeaveTypeMappingError(Exception):
    """A leave_type_mapping.toml entry has no matching type on this tenant."""


def _load_mapping() -> dict[str, str]:
    with _TABLE_PATH.open("rb") as f:
        raw = tomllib.load(f)
    return dict(raw["leave_type_mapping"])


LEAVE_TYPE_MAPPING: dict[str, str] = _load_mapping()
BAMBOOHR_NAME_TO_DOMAIN_TYPE: dict[str, str] = {v: k for k, v in LEAVE_TYPE_MAPPING.items()}


def validate_leave_type_mapping(configured_type_names: set[str]) -> None:
    """Raises if any configured mapping targets a type this tenant doesn't have.

    A silent mismatch here doesn't fail loudly on its own -- get_time_off_taken
    would just find zero matching requests and report a balance as if no days
    had been taken, which is the one failure mode worse than an error.
    """
    unknown = {
        domain_key: bamboohr_name
        for domain_key, bamboohr_name in LEAVE_TYPE_MAPPING.items()
        if bamboohr_name not in configured_type_names
    }
    if unknown:
        raise LeaveTypeMappingError(
            f"leave_type_mapping.toml maps {unknown} but this tenant's configured "
            f"time-off types are {sorted(configured_type_names)}"
        )
