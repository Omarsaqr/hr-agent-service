from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # No default: an unset ENVIRONMENT should fail startup, not silently
    # serve production traffic under local-mode assumptions.
    environment: Literal["local", "test", "production"]
    log_level: str = "INFO"

    # Defaults to memory, not required: every environment that doesn't
    # care about BambooHR (tests, local dev, CI) should work with zero
    # extra config, not have to opt out of a real credential requirement.
    hris_driver: Literal["memory", "bamboohr"] = "memory"
    bamboohr_subdomain: str | None = None
    # SecretStr: a credential, not just data -- kept out of reprs/str()
    # the same way birth_date is kept out via repr=False, but via the
    # type itself since this one is worth enforcing everywhere, not just
    # on one dataclass.
    bamboohr_api_key: SecretStr | None = None

    # Same "memory by default, opt in to the real vendor" shape as
    # hris_driver. The credential here is a file path, not a SecretStr:
    # the secret itself is the service-account JSON key file on disk,
    # never a value that passes through this process's environment.
    dashboard_driver: Literal["memory", "sheets"] = "memory"
    google_sheets_credentials_path: str | None = None
    google_sheets_spreadsheet_id: str | None = None
    google_sheets_sheet_name: str = "checkins"

    # No default, deliberately: a hardcoded fallback would make every
    # preview token signature forgeable by anyone who reads the source.
    # Missing this must fail startup, not silently sign with a known key.
    preview_token_secret: SecretStr

    # Off by default so tests and CI never accidentally start a
    # background scheduler thread -- opt in explicitly to see it run.
    iqama_scheduler_enabled: bool = False

    # Same "memory by default" shape as the other drivers -- "mock" is a
    # deterministic, credential-free stand-in (see
    # app/integrations/llm/mock.py), not a placeholder that fails
    # without a real key. gemini-2.5-flash is confirmed free-tier
    # eligible as of this writing but is scheduled to shut down on
    # 2026-10-16; if that's already passed, set GEMINI_MODEL to whatever
    # Google's current free-tier Flash model is rather than editing code.
    llm_driver: Literal["mock", "gemini"] = "mock"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"

    model_config = SettingsConfigDict(env_file=".env")
