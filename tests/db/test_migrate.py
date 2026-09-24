"""The migration runner and the seed loader."""

import asyncpg
import pytest

from intake.db import migrate, seed
from intake.db.migrate import Migration, MigrationError, apply_migrations, read_migrations
from intake.db.seed import SeedError, apply_seed, read_seed


async def test_second_run_is_a_no_op(raw: asyncpg.Connection):
    assert await apply_migrations(raw, read_migrations()) == []
    assert await raw.fetchval("SELECT count(*) FROM schema_migrations") == 1


async def test_an_edited_migration_is_refused(raw: asyncpg.Connection):
    edited = Migration("0001_init.sql", "-- edited after it was applied")

    with pytest.raises(MigrationError, match=r"0001_init\.sql changed after it was applied"):
        await apply_migrations(raw, [edited])


def test_line_endings_do_not_change_the_checksum():
    migration = read_migrations()[0]
    crlf = Migration(migration.name, migration.sql.replace("\n", "\r\n"))

    assert crlf.checksum == migration.checksum


async def test_a_failed_migration_is_rolled_back_and_not_recorded(raw: asyncpg.Connection):
    broken = Migration("9999_broken.sql", "CREATE TABLE half_done (x int); SELECT 1 / 0;")

    with pytest.raises(MigrationError, match=r"9999_broken\.sql failed"):
        await apply_migrations(raw, [broken])

    assert await raw.fetchval("SELECT to_regclass('half_done')") is None
    assert await raw.fetchval("SELECT count(*) FROM schema_migrations") == 1


async def test_seed_can_run_twice(raw: asyncpg.Connection):
    await apply_seed(raw, read_seed())
    await apply_seed(raw, read_seed())

    counts = await raw.fetchrow(
        "SELECT (SELECT count(*) FROM patients) AS patients,"
        " (SELECT count(*) FROM doctors) AS doctors,"
        " (SELECT count(*) FROM doctor_schedules) AS schedules"
    )
    assert dict(counts) == {"patients": 2, "doctors": 3, "schedules": 22}


async def test_a_failed_seed_is_reported(raw: asyncpg.Connection):
    with pytest.raises(SeedError, match="seed failed"):
        await apply_seed(raw, "INSERT INTO no_such_table VALUES (1)")


def test_commands_report_success(database_url: str, capsys: pytest.CaptureFixture[str]):
    assert migrate.main(["--test"]) == 0
    assert seed.main(["--test"]) == 0

    assert capsys.readouterr().out == "ok (already up to date)\nok\n"
