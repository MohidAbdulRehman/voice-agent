"""Async database access for Postgres over asyncpg: a SQLAlchemy engine, or a raw connection."""

import asyncpg
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

_POSTGRES_DRIVERS = {"postgres", "postgresql", "postgresql+asyncpg"}
CONNECT_TIMEOUT_SECONDS = 15


def to_async_url(url: str) -> URL:
    """Parse a Postgres URL and switch it to the asyncpg driver.

    Providers hand out ``postgresql://`` (or ``postgres://``) URLs, while SQLAlchemy
    needs ``postgresql+asyncpg://``. The returned ``URL`` masks the password when
    printed, and errors never include the URL because it holds the password.

    Raises:
        ValueError: ``url`` can't be parsed or isn't a Postgres URL.
    """
    try:
        parsed = make_url(url)
    except (ArgumentError, ValueError):
        raise ValueError("database URL could not be parsed") from None
    if parsed.drivername not in _POSTGRES_DRIVERS:
        raise ValueError(f"database URL must start with postgresql://, not {parsed.drivername}://")
    return parsed.set(drivername="postgresql+asyncpg")


def make_engine(url: str) -> AsyncEngine:
    """Create an async engine for a Postgres ``url`` in any of the accepted forms.

    Statement parameters are hidden from error messages, so a failed write never
    puts patient data into a log line. A connection attempt gives up after
    CONNECT_TIMEOUT_SECONDS instead of asyncpg's default minute, so an
    unreachable database fails a request quickly.
    """
    return create_async_engine(
        to_async_url(url),
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"timeout": CONNECT_TIMEOUT_SECONDS},
    )


async def connect(url: str) -> asyncpg.Connection:
    """Open a raw asyncpg connection, for SQL scripts (migrations, seed) and LISTEN."""
    dsn = to_async_url(url).set(drivername="postgresql").render_as_string(hide_password=False)
    return await asyncpg.connect(dsn, timeout=CONNECT_TIMEOUT_SECONDS)
