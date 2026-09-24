"""Database connectivity check: prints ``ok`` when the database answers ``SELECT 1``.

Usage::

    uv run python -m intake.db.check          # DATABASE_URL
    uv run python -m intake.db.check --test   # TEST_DATABASE_URL (local Docker Postgres)

On failure it prints only the error class. It never prints the URL, which holds
the password.
"""

import argparse
import asyncio
import sys

from sqlalchemy import text

from intake.config import get_settings
from intake.db.engine import make_engine

TIMEOUT_SECONDS = 15


async def check(url: str) -> None:
    """Connect to ``url`` and run ``SELECT 1``, raising on any failure."""
    engine = make_engine(url)
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS), engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    """Run the check from the command line and return the process exit code."""
    parser = argparse.ArgumentParser(
        prog="python -m intake.db.check",
        description="Print 'ok' if the database answers SELECT 1.",
    )
    parser.add_argument(
        "--test", action="store_true", help="check TEST_DATABASE_URL instead of DATABASE_URL"
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    name = "TEST_DATABASE_URL" if args.test else "DATABASE_URL"
    url = settings.test_database_url if args.test else settings.database_url
    if url is None:
        print(f"error: {name} is not set", file=sys.stderr)
        return 1
    try:
        asyncio.run(check(url.get_secret_value()))
    except Exception as exc:
        print(f"error: could not connect using {name} ({type(exc).__name__})", file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
