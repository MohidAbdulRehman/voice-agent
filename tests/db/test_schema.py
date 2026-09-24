"""Schema behaviour: column parity, idempotency, triggers, NOTIFY and double-booking."""

import asyncio
import json
from datetime import timedelta

import asyncpg
import pytest

from intake.core.repository import metadata
from intake.db.engine import connect
from tests.db.helpers import AVERY, INSERT_PATIENT, LUIS, REED, SHAH, at, upcoming


@pytest.mark.parametrize("table", metadata.tables.values(), ids=lambda t: t.name)
async def test_repository_columns_match_the_schema(raw: asyncpg.Connection, table: object):
    rows = await raw.fetch(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_schema = 'public' AND table_name = $1",
        table.name,
    )

    assert {row["column_name"] for row in rows} == set(table.c.keys())


async def test_one_call_creates_at_most_one_patient(raw: asyncpg.Connection):
    call_id = await raw.fetchval(
        "INSERT INTO calls (room_name) VALUES ('room-1') RETURNING call_id"
    )
    await raw.fetchval(INSERT_PATIENT, call_id)

    with pytest.raises(asyncpg.UniqueViolationError) as excinfo:
        await raw.fetchval(INSERT_PATIENT, call_id)

    assert excinfo.value.constraint_name == "patients_source_call_id_key"


async def test_updated_at_moves_on_every_update(raw: asyncpg.Connection):
    patient_id = await raw.fetchval(INSERT_PATIENT, None)
    before = await raw.fetchval("SELECT updated_at FROM patients WHERE patient_id = $1", patient_id)

    await raw.execute("UPDATE patients SET city = 'Dallas' WHERE patient_id = $1", patient_id)

    after = await raw.fetchval("SELECT updated_at FROM patients WHERE patient_id = $1", patient_id)
    assert after > before


async def test_changes_are_announced_without_patient_data(
    raw: asyncpg.Connection, database_url: str
):
    events: asyncio.Queue[str] = asyncio.Queue()
    listener = await connect(database_url)
    await listener.add_listener("intake_changes", lambda *args: events.put_nowait(args[-1]))
    try:
        await raw.execute("INSERT INTO calls (room_name) VALUES ('room-1')")
        patient_id = await raw.fetchval(INSERT_PATIENT, None)
        await raw.execute("UPDATE patients SET city = 'Dallas' WHERE patient_id = $1", patient_id)
        await raw.execute("DELETE FROM patients WHERE patient_id = $1", patient_id)
        received = [json.loads(await asyncio.wait_for(events.get(), 5)) for _ in range(4)]
    finally:
        await listener.close()

    assert received == [
        {"table": "calls", "op": "INSERT"},
        {"table": "patients", "op": "INSERT"},
        {"table": "patients", "op": "UPDATE"},
        {"table": "patients", "op": "DELETE"},
    ]


async def _book(
    raw: asyncpg.Connection, patient_id: object, doctor_id: object, start: object
) -> None:
    await raw.execute(
        "INSERT INTO appointments (patient_id, doctor_id, starts_at, ends_at, booked_via)"
        " VALUES ($1, $2, $3, $3::timestamptz + interval '30 minutes', 'api')",
        patient_id,
        doctor_id,
        start,
    )


@pytest.mark.usefixtures("seeded")
async def test_a_doctor_cannot_be_double_booked(raw: asyncpg.Connection):
    ten = at(upcoming(0), 10)
    await _book(raw, AVERY, SHAH, ten)

    with pytest.raises(asyncpg.ExclusionViolationError) as excinfo:
        await _book(raw, LUIS, SHAH, ten + timedelta(minutes=15))

    assert excinfo.value.constraint_name == "no_doctor_double_booking"


@pytest.mark.usefixtures("seeded")
async def test_a_patient_cannot_be_double_booked(raw: asyncpg.Connection):
    ten = at(upcoming(0), 10)
    await _book(raw, AVERY, SHAH, ten)

    with pytest.raises(asyncpg.ExclusionViolationError) as excinfo:
        await _book(raw, AVERY, REED, ten)

    assert excinfo.value.constraint_name == "no_patient_double_booking"


@pytest.mark.usefixtures("seeded")
async def test_back_to_back_bookings_are_allowed(raw: asyncpg.Connection):
    ten = at(upcoming(0), 10)
    await _book(raw, AVERY, SHAH, ten)
    await _book(raw, LUIS, SHAH, ten + timedelta(minutes=30))

    assert await raw.fetchval("SELECT count(*) FROM appointments") == 2


@pytest.mark.usefixtures("seeded")
async def test_cancelling_frees_the_slot(raw: asyncpg.Connection):
    ten = at(upcoming(0), 10)
    await _book(raw, AVERY, SHAH, ten)
    await raw.execute("UPDATE appointments SET status = 'cancelled'")

    await _book(raw, LUIS, SHAH, ten)

    assert await raw.fetchval("SELECT count(*) FROM appointments WHERE status = 'scheduled'") == 1
