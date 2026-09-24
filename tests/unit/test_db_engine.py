"""Postgres URLs switch to asyncpg, and the password never shows up in output or errors."""

import pytest

from intake.db.engine import to_async_url


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
