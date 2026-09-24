"""Suite-wide guardrails.

Tests never touch the real (Supabase) database. Before any test module is imported,
DATABASE_URL is pointed at TEST_DATABASE_URL (the local Docker Postgres), so code
that reads DATABASE_URL during a test can only ever reach the test database.
"""

import logging
import os
from collections.abc import Iterator

import pytest
import structlog

from intake.config import Settings, get_settings

pytest_plugins = ("tests.database",)


def pytest_configure(config: pytest.Config) -> None:
    os.environ["DATABASE_URL"] = Settings().test_database_url.get_secret_value()


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    """Rebuild settings for every test, so environment changes made by a test apply."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def restore_logging() -> Iterator[None]:
    """Undo configure_logging after the test, leaving pytest's own capture handlers alone."""
    root = logging.getLogger()
    level = root.level
    libraries = [logging.getLogger(name) for name in ("uvicorn", "uvicorn.error", "uvicorn.access")]
    saved = [(lib.handlers[:], lib.propagate, lib.disabled) for lib in libraries]
    yield
    for handler in root.handlers[:]:
        if isinstance(handler.formatter, structlog.stdlib.ProcessorFormatter):
            root.removeHandler(handler)
    root.setLevel(level)
    for library, (handlers, propagate, disabled) in zip(libraries, saved, strict=True):
        library.handlers, library.propagate, library.disabled = handlers, propagate, disabled
    structlog.reset_defaults()
