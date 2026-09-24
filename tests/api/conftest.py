"""API fixtures: the app wired to the test database, and an in-process httpx client for it."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from intake.api.main import create_app
from intake.api.ratelimit import limiter
from intake.config import Settings
from intake.core.services import Services, build_services
from intake.db.engine import make_engine
from tests.db.helpers import NOW


def build_app(services: Services, dashboard_dir: Path, **settings: object) -> FastAPI:
    """A fresh app on ``services``, with fresh rate-limit counters and settings that ignore .env."""
    limiter.reset()
    return create_app(
        Settings(_env_file=None, **settings), services=services, dashboard_dir=dashboard_dir
    )


@asynccontextmanager
async def client_for(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """An httpx client that calls ``app`` in-process."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def services(engine: AsyncEngine) -> Services:
    """Services on the test database, with "today" pinned to NOW at the clinic."""
    return build_services(engine, Settings(_env_file=None), clock=lambda: NOW)


@pytest.fixture
def app(services: Services, tmp_path: Path) -> FastAPI:
    """The app on the test database, without a built dashboard."""
    return build_app(services, tmp_path)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with client_for(app) as client:
        yield client


@pytest.fixture
async def unreachable() -> AsyncIterator[Services]:
    """Services whose database refuses every connection."""
    engine = make_engine("postgresql://postgres:postgres@127.0.0.1:5433/unreachable_test")

    @event.listens_for(engine.sync_engine, "do_connect")
    def _refuse(*_args: object) -> None:
        raise ConnectionRefusedError("the database is down")

    yield build_services(engine, Settings(_env_file=None))
    await engine.dispose()
