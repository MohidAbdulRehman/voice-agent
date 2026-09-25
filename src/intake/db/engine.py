"""Async database access for Postgres over asyncpg: a SQLAlchemy engine, or a raw connection."""

from typing import Any
from uuid import uuid4

import asyncpg
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

_POSTGRES_DRIVERS = {"postgres", "postgresql", "postgresql+asyncpg"}
CONNECT_TIMEOUT_SECONDS = 15
# Supabase's transaction-mode pooler listens on 6543; its session-mode pooler and
# direct connections use 5432.
TRANSACTION_POOLER_PORT = 6543


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

    A URL on port 6543 is Supabase's transaction pooler, which the serverless API
    uses. A pooled server connection is only ours for one transaction, so prepared
    statements get unique names and are never cached, and there is no client-side
    pool: the pooler is the pool, and a paused serverless instance can't keep
    connections alive anyway.
    """
    parsed = to_async_url(url)
    connect_args: dict[str, Any] = {"timeout": CONNECT_TIMEOUT_SECONDS}
    if parsed.port == TRANSACTION_POOLER_PORT:
        connect_args |= {
            "statement_cache_size": 0,  # asyncpg's own statement cache
            "prepared_statement_cache_size": 0,  # SQLAlchemy's asyncpg adapter cache
            "prepared_statement_name_func": _unique_statement_name,
        }
        return create_async_engine(
            parsed, poolclass=NullPool, hide_parameters=True, connect_args=connect_args
        )
    return create_async_engine(
        parsed, pool_pre_ping=True, hide_parameters=True, connect_args=connect_args
    )


def _unique_statement_name() -> str:
    # asyncpg numbers statements per connection, so two clients sharing a pooled
    # server connection would collide on "__asyncpg_stmt_1__".
    return f"__asyncpg_{uuid4().hex}__"


async def connect(url: str) -> asyncpg.Connection:
    """Open a raw asyncpg connection, for SQL scripts (migrations, seed)."""
    dsn = to_async_url(url).set(drivername="postgresql").render_as_string(hide_password=False)
    return await asyncpg.connect(dsn, timeout=CONNECT_TIMEOUT_SECONDS)
