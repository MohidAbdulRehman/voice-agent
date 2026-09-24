"""Load the fictional demo data in db/seed.sql. Safe to run repeatedly.

Usage::

    uv run python -m intake.db.seed          # DATABASE_URL
    uv run python -m intake.db.seed --test   # TEST_DATABASE_URL

The seed uses fixed ids with ON CONFLICT DO NOTHING, so a second run changes nothing.
"""

import asyncio
import sys
from pathlib import Path

import asyncpg

from intake.db.cli import target_database
from intake.db.engine import connect

SEED_FILE = Path(__file__).resolve().parents[3] / "db" / "seed.sql"


class SeedError(Exception):
    """The seed SQL failed (it's rolled back)."""


def read_seed(path: Path = SEED_FILE) -> str:
    """The seed SQL."""
    return path.read_text(encoding="utf-8")


async def apply_seed(conn: asyncpg.Connection, sql: str) -> None:
    """Run the seed SQL in one transaction.

    Raises:
        SeedError: the SQL failed, e.g. because the migrations haven't been applied.
    """
    try:
        async with conn.transaction():
            await conn.execute(sql)
    except asyncpg.PostgresError as exc:
        raise SeedError(f"seed failed: {exc}") from exc


async def _seed(url: str, sql: str) -> None:
    conn = await connect(url)
    try:
        await apply_seed(conn, sql)
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    """Load the seed data from the command line and return the process exit code."""
    target = target_database("python -m intake.db.seed", "Load the demo data in db/seed.sql.", argv)
    if target is None:
        return 1
    name, url = target
    try:
        asyncio.run(_seed(url, read_seed()))
    except SeedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: could not seed using {name} ({type(exc).__name__})", file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
