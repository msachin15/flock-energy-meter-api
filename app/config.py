"""Environment configuration.

Credentials are read from the environment or a local .env file.
They are never hardcoded and the password is wrapped so it does not appear in repr().
"""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    portal_base_url: str = "https://urja-ops.flockenergy.tech"
    portal_email: str = ""
    portal_password: SecretStr = SecretStr("")
    portal_timeout_seconds: float = 15
    cache_ttl_seconds: float = 300

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator("portal_base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        """Strip a trailing slash and require an http or https origin."""

        text = value.strip().rstrip("/")
        if not text.startswith(("http://", "https://")):
            raise ValueError("PORTAL_BASE_URL must start with http:// or https://")
        return text

    @field_validator("portal_timeout_seconds")
    @classmethod
    def timeout_must_be_positive(cls, value: float) -> float:
        """Reject a zero or negative portal timeout."""

        if value <= 0:
            raise ValueError("PORTAL_TIMEOUT_SECONDS must be greater than zero")
        return value

    @field_validator("cache_ttl_seconds")
    @classmethod
    def cache_ttl_cannot_be_negative(cls, value: float) -> float:
        """Allow zero, which refreshes on every read. Reject a negative TTL."""

        if value < 0:
            raise ValueError("CACHE_TTL_SECONDS cannot be negative")
        return value


@lru_cache
def get_settings() -> Settings:
    """Load settings once per process. Tests that need other values construct Settings directly."""

    return Settings()
