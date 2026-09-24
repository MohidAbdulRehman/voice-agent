"""Apply db/migrations/*.sql in filename order, each file in its own transaction.

Usage::

    uv run python -m intake.db.migrate          # DATABASE_URL
    uv run python -m intake.db.migrate --test   # TEST_DATABASE_URL

Applied files are recorded in ``schema_migrations`` with a checksum, so a second
run is a no-op and editing an applied file is an error instead of silent drift.
An advisory lock stops two runners from applying the same file.
"""

import asyncio
import hashlib
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import asyncpg

from intake.db.cli import target_database
from intake.db.engine import connect

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "db" / "migrations"
_LOCK_KEY = 7_202_609_240  # any fixed bigint shared by every runner

# schema_migrations gets RLS like the app tables, which hides it from Supabase's Data API.
_BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version    text        PRIMARY KEY,
  checksum   text        NOT NULL,
  applied_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE schema_migrations ENABLE ROW LEVEL SECURITY;
"""


class MigrationError(Exception):
    """A migration failed, or an applied migration file was edited."""


@dataclass(frozen=True)
class Migration:
    """One migration file: its name (the version) and its SQL."""

    name: str
    sql: str

    @property
    def checksum(self) -> str:
        """SHA-256 of the SQL, ignoring CRLF versus LF line endings."""
        return hashlib.sha256(self.sql.replace("\r\n", "\n").encode()).hexdigest()


def read_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """The migration files in ``directory``, in the order they apply."""
    return [
        Migration(path.name, path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.sql"))
    ]


async def apply_migrations(conn: asyncpg.Connection, migrations: Sequence[Migration]) -> list[str]:
    """Apply every migration not yet recorded, in order.

    Returns:
        The names this run applied; empty when already up to date.

    Raises:
        MigrationError: a migration failed (it's rolled back), or an applied one changed.
    """
    async with conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock($1)", _LOCK_KEY)
        await conn.execute(_BOOTSTRAP)
    applied = []
    for migration in migrations:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", _LOCK_KEY)
            recorded = await conn.fetchval(
                "SELECT checksum FROM schema_migrations WHERE version = $1", migration.name
            )
            if recorded is not None:
                if recorded != migration.checksum:
                    raise MigrationError(f"{migration.name} changed after it was applied")
                continue
            try:
                await conn.execute(migration.sql)
            except asyncpg.PostgresError as exc:
                raise MigrationError(f"{migration.name} failed: {exc}") from exc
            await conn.execute(
                "INSERT INTO schema_migrations (version, checksum) VALUES ($1, $2)",
                migration.name,
                migration.checksum,
            )
        applied.append(migration.name)
    return applied


async def _migrate(url: str, migrations: Sequence[Migration]) -> list[str]:
    conn = await connect(url)
    try:
        return await apply_migrations(conn, migrations)
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    """Run pending migrations from the command line and return the process exit code."""
    target = target_database(
        "python -m intake.db.migrate", "Apply pending migrations from db/migrations.", argv
    )
    if target is None:
        return 1
    name, url = target
    try:
        applied = asyncio.run(_migrate(url, read_migrations()))
    except MigrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: could not migrate using {name} ({type(exc).__name__})", file=sys.stderr)
        return 1
    for version in applied:
        print(f"applied {version}")
    print("ok" if applied else "ok (already up to date)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
