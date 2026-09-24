"""HealthService: whether the database answers."""

from sqlalchemy.ext.asyncio import AsyncEngine

from intake.core.repository import Repository
from intake.core.services import HealthService
from intake.db.engine import make_engine


async def test_a_reachable_database_is_ok(engine: AsyncEngine):
    assert await HealthService(Repository(engine)).database_ok()


async def test_an_unreachable_database_is_not_ok():
    engine = make_engine("postgresql://postgres:postgres@127.0.0.1:1/intake_test")
    try:
        assert not await HealthService(Repository(engine)).database_ok()
    finally:
        await engine.dispose()
