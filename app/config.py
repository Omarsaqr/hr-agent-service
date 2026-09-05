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

    model_config = SettingsConfigDict(env_file=".env")
