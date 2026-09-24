"""Database fixtures, shared by the db, api and agent tests (registered in tests/conftest.py).

The test database is rebuilt once per run and emptied before each test. The
fixtures refuse to touch anything but a local database whose name ends in ``_test``.
"""

import asyncio
from collections.abc import AsyncIterator

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from intake.config import Settings
from intake.core.repository import Repository
from intake.core.services import CallService, PatientService, SchedulingService
from intake.db.engine import connect, make_engine, to_async_url
from intake.db.migrate import apply_migrations, read_migrations
from intake.db.seed import apply_seed, read_seed
from tests.db.helpers import EASTERN, NOW

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _require_disposable(url: str) -> None:
    parsed = to_async_url(url)
    if parsed.host not in LOCAL_HOSTS or not (parsed.database or "").endswith("_test"):
        pytest.exit(
            "TEST_DATABASE_URL must be a local database named *_test; refusing to reset it.",
            returncode=2,
        )


async def _rebuild(url: str) -> None:
    conn = await connect(url)
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await apply_migrations(conn, read_migrations())
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def database_url() -> str:
    """TEST_DATABASE_URL, reset to a freshly migrated schema once per test run."""
    url = Settings().test_database_url.get_secret_value()
    _require_disposable(url)
    asyncio.run(_rebuild(url))
    return url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    """An engine on the test database, after every table was emptied."""
    engine = make_engine(database_url)
    async with engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE appointments, doctor_schedules, doctors, patients, calls")
        )
    yield engine
    await engine.dispose()


@pytest.fixture
async def raw(database_url: str, engine: AsyncEngine) -> AsyncIterator[asyncpg.Connection]:
    """A raw asyncpg connection to the (emptied) test database, for direct SQL."""
    conn = await connect(database_url)
    yield conn
    await conn.close()


@pytest.fixture
async def seeded(raw: asyncpg.Connection) -> None:
    """Load the demo data from db/seed.sql."""
    await apply_seed(raw, read_seed())


@pytest.fixture
def repository(engine: AsyncEngine) -> Repository:
    return Repository(engine)


@pytest.fixture
def patients(repository: Repository) -> PatientService:
    """Patients, with "today" pinned to NOW at the clinic."""
    return PatientService(repository, timezone=EASTERN, clock=lambda: NOW)


@pytest.fixture
def calls(repository: Repository) -> CallService:
    return CallService(repository)


@pytest.fixture
def scheduling(repository: Repository) -> SchedulingService:
    """Scheduling on the real clock: available_slots() compares with the database's now()."""
    return SchedulingService(repository, timezone=EASTERN)
