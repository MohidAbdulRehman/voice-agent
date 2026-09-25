"""Postgres URLs switch to asyncpg, the password never shows up, and poolers get the right settings."""

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import NullPool

from intake.db.engine import CONNECT_TIMEOUT_SECONDS, make_engine, to_async_url

POOLER_SETTINGS = {
    "statement_cache_size",
    "prepared_statement_cache_size",
    "prepared_statement_name_func",
}


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://app:s3cret@db.example.com:5432/intake",
        "postgres://app:s3cret@db.example.com:5432/intake",
        "postgresql+asyncpg://app:s3cret@db.example.com:5432/intake",
    ],
)
def test_postgres_urls_use_asyncpg(url: str):
    parsed = to_async_url(url)

    assert parsed.drivername == "postgresql+asyncpg"
    assert (parsed.username, parsed.password, parsed.host, parsed.port, parsed.database) == (
        "app",
        "s3cret",
        "db.example.com",
        5432,
        "intake",
    )


def test_printed_url_masks_the_password():
    assert "s3cret" not in str(to_async_url("postgresql://app:s3cret@localhost/intake"))


@pytest.mark.parametrize(
    "url",
    [
        "mysql://app:s3cret@localhost/intake",
        "app:s3cret@@not a url",
        "postgresql://app:s3cret@localhost:not-a-port/intake",
    ],
)
def test_rejected_urls_never_echo_the_password(url: str):
    with pytest.raises(ValueError, match="database URL") as excinfo:
        to_async_url(url)

    assert "s3cret" not in str(excinfo.value)


async def _connect_args(engine: AsyncEngine) -> dict[str, object]:
    """The keyword arguments the engine hands the driver, captured without connecting."""
    captured: dict[str, object] = {}

    @event.listens_for(engine.sync_engine, "do_connect")
    def _capture(_dialect: object, _record: object, _cargs: object, cparams: dict) -> None:
        captured.update(cparams)
        raise ConnectionRefusedError  # stop before any network I/O

    with pytest.raises(ConnectionRefusedError):
        async with engine.connect():
            pass
    await engine.dispose()
    return captured


async def test_the_transaction_pooler_gets_no_pool_and_no_reused_statements():
    engine = make_engine("postgresql://app:s3cret@pooler.example.com:6543/postgres")

    assert isinstance(engine.pool, NullPool)
    args = await _connect_args(engine)
    assert args["statement_cache_size"] == 0
    assert args["prepared_statement_cache_size"] == 0
    assert args["timeout"] == CONNECT_TIMEOUT_SECONDS
    name = args["prepared_statement_name_func"]
    assert callable(name)
    assert name() != name()


@pytest.mark.parametrize("port", [5432, 5433])
async def test_other_ports_keep_a_pool_and_the_statement_cache(port: int):
    engine = make_engine(f"postgresql://app:s3cret@db.example.com:{port}/postgres")

    assert not isinstance(engine.pool, NullPool)
    args = await _connect_args(engine)
    assert args["timeout"] == CONNECT_TIMEOUT_SECONDS
    assert not POOLER_SETTINGS & args.keys()
