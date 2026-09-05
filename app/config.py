from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # No default: an unset ENVIRONMENT should fail startup, not silently
    # serve production traffic under local-mode assumptions.
    environment: Literal["local", "test", "production"]
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env")
