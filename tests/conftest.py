import pytest

from app.config import Settings


@pytest.fixture
def settings() -> Settings:
    """Settings for unit tests. Does not read the developer .env file."""

    return Settings(
        portal_base_url="https://portal.test",
        portal_email="user@example.com",
        portal_password="synthetic-password",
        portal_timeout_seconds=5,
        cache_ttl_seconds=300,
        _env_file=None,
    )
