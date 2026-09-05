from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_missing_environment_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    # _env_file=None: ignore any real .env on disk so this checks the
    # no-var case specifically, not whichever value a local file supplies.
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_reads_environment_from_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")

    settings = Settings(_env_file=None)

    assert settings.environment == "production"
    assert settings.log_level == "INFO"


def test_hris_driver_defaults_to_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.delenv("HRIS_DRIVER", raising=False)

    assert Settings(_env_file=None).hris_driver == "memory"


def test_bamboohr_api_key_is_not_exposed_by_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("BAMBOOHR_API_KEY", "super-secret-value")

    settings = Settings(_env_file=None)

    assert "super-secret-value" not in repr(settings)
    assert settings.bamboohr_api_key is not None
    assert settings.bamboohr_api_key.get_secret_value() == "super-secret-value"


def test_unrecognised_env_file_vars_are_rejected_not_silently_ignored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # extra="forbid" applies to keys sourced from the .env *file* --
    # pydantic-settings deliberately does not extend this to the wider
    # OS environment, which legitimately carries unrelated variables
    # (PATH, HOME, ...). A typo'd key in .env itself should still fail
    # startup loudly, the same way a missing ENVIRONMENT does.
    monkeypatch.setenv("ENVIRONMENT", "test")
    env_file = tmp_path / ".env"
    env_file.write_text("SOME_TYPO_OF_A_SETTING=value\n")

    with pytest.raises(ValidationError):
        Settings(_env_file=env_file)
