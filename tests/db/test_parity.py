"""The database rejects what the Python rules reject (docs/specs/data-model.md)."""

import re
from datetime import date, datetime
from enum import StrEnum

import asyncpg
import pytest
from sqlalchemy import insert
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from intake.core.models import AppointmentStatus, CallStatus, Sex
from intake.core.repository import patients
from intake.core.states import STATE_NAMES
from tests.cases import REJECTED, Rejected

VALID_ROW = {
    "first_name": "Jane",
    "last_name": "Doe",
    "date_of_birth": date(1990, 3, 5),
    "sex": "Female",
    "phone_number": "5125550100",
    "address_line_1": "1 Main St",
    "city": "Austin",
    "state": "TX",
    "zip_code": "78701",
}
ENFORCED = [example for example in REJECTED if example.constraint is not None]


def _stored(example: Rejected) -> object:
    if example.field == "date_of_birth":
        return datetime.strptime(example.value, "%m/%d/%Y").date()  # noqa: DTZ007 - a date, no time
    return example.value


async def test_the_valid_row_is_accepted(engine: AsyncEngine):
    async with engine.begin() as conn:
        await conn.execute(insert(patients).values(**VALID_ROW))


@pytest.mark.parametrize("example", ENFORCED, ids=lambda e: f"{e.constraint}:{e.value[:20]!r}")
async def test_a_constraint_rejects_what_python_rejects(engine: AsyncEngine, example: Rejected):
    row = {**VALID_ROW, example.field: _stored(example)}

    with pytest.raises(IntegrityError) as excinfo:
        async with engine.begin() as conn:
            await conn.execute(insert(patients).values(**row))

    assert excinfo.value.orig.sqlstate == "23514"  # check_violation
    assert excinfo.value.orig.__cause__.constraint_name == example.constraint


async def test_the_sex_enum_rejects_other_values(engine: AsyncEngine):
    with pytest.raises(DBAPIError) as excinfo:
        async with engine.begin() as conn:
            await conn.execute(insert(patients).values(**{**VALID_ROW, "sex": "F"}))

    assert excinfo.value.orig.sqlstate == "22P02"  # invalid input value for enum


async def test_state_codes_match_the_constraint(raw: asyncpg.Connection):
    definition = await raw.fetchval(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'state_valid'"
    )

    assert set(re.findall(r"'([A-Z]{2})'", definition)) == set(STATE_NAMES)


@pytest.mark.parametrize(
    ("type_name", "python_enum"),
    [("sex_type", Sex), ("call_status", CallStatus), ("appointment_status", AppointmentStatus)],
)
async def test_python_enums_match_the_database(
    raw: asyncpg.Connection, type_name: str, python_enum: type[StrEnum]
):
    labels = await raw.fetchval(
        "SELECT array_agg(e.enumlabel::text ORDER BY e.enumsortorder)"
        " FROM pg_enum AS e JOIN pg_type AS t ON t.oid = e.enumtypid WHERE t.typname = $1",
        type_name,
    )

    assert labels == [member.value for member in python_enum]
