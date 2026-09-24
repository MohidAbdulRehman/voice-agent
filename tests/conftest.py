"""Suite-wide guardrails.

Tests never touch the real (Supabase) database. Before any test module is imported,
DATABASE_URL is pointed at TEST_DATABASE_URL (the local Docker Postgres), so code
that reads DATABASE_URL during a test can only ever reach the test database.
"""

import os
from collections.abc import Iterator

import pytest

from intake.config import Settings, get_settings


def pytest_configure(config: pytest.Config) -> None:
    os.environ["DATABASE_URL"] = Settings().test_database_url.get_secret_value()


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    """Rebuild settings for every test, so environment changes made by a test apply."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
