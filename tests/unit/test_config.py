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
