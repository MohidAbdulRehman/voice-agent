"""available_slots(): schedules minus bookings, in the clinic's time zone."""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import asyncpg
import pytest

from tests.db.helpers import AVERY, EASTERN, REED, RUIZ, SHAH, at, upcoming


async def _slots(
    raw: asyncpg.Connection, start: date, days: int, doctor_id: UUID | None = None
) -> list[asyncpg.Record]:
    return await raw.fetch(
        "SELECT slot_doctor_id, slot_start, slot_end FROM available_slots($1, $2, $3, $4)",
        start,
        days,
        doctor_id,
        "America/New_York",
    )


def _first_sunday_of_november(year: int) -> date:
    first = date(year, 11, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7)


def _utc(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


@pytest.mark.usefixtures("seeded")
async def test_slots_follow_each_doctors_weekdays(raw: asyncpg.Connection):
    rows = await _slots(raw, upcoming(0), 7, RUIZ)

    assert {row["slot_start"].astimezone(EASTERN).weekday() for row in rows} == {1, 3}  # Tue, Thu
    assert len(rows) == 2 * 14  # 9:00-16:00 in 30-minute slots
    assert all(row["slot_end"] - row["slot_start"] == timedelta(minutes=30) for row in rows)


@pytest.mark.usefixtures("seeded")
async def test_slots_keep_clinic_hours_across_the_dst_change(raw: asyncpg.Connection):
    sunday = _first_sunday_of_november(datetime.now(UTC).year + 1)
    friday, monday = sunday - timedelta(days=2), sunday + timedelta(days=1)

    by_day: dict[date, list[datetime]] = defaultdict(list)
    for row in await _slots(raw, friday, 4, SHAH):
        by_day[row["slot_start"].astimezone(EASTERN).date()].append(row["slot_start"])

    assert sorted(by_day) == [friday, monday]  # nothing on the weekend
    assert len(by_day[friday]) == len(by_day[monday]) == 14
    assert min(by_day[friday]) == _utc(friday, 13)  # 9 AM EDT is UTC-4
    assert min(by_day[monday]) == _utc(monday, 14)  # 9 AM EST is UTC-5


@pytest.mark.usefixtures("seeded")
async def test_booked_slots_are_not_offered(raw: asyncpg.Connection):
    monday = upcoming(0)
    nine = at(monday, 9)
    await raw.execute(
        "INSERT INTO appointments (patient_id, doctor_id, starts_at, ends_at, booked_via)"
        " VALUES ($1, $2, $3, $3::timestamptz + interval '30 minutes', 'api')",
        AVERY,
        SHAH,
        nine,
    )

    offered = {(row["slot_doctor_id"], row["slot_start"]) for row in await _slots(raw, monday, 1)}

    assert (SHAH, nine) not in offered
    assert (REED, nine) in offered


async def test_slots_start_at_least_an_hour_from_now(raw: asyncpg.Connection):
    doctor_id = await raw.fetchval(
        "INSERT INTO doctors (full_name, specialty) VALUES ('Dr. Always Open', 'Testing')"
        " RETURNING doctor_id"
    )
    await raw.execute(
        "INSERT INTO doctor_schedules (doctor_id, day_of_week, start_time, end_time)"
        " SELECT $1, day, '00:00', '24:00' FROM generate_series(1, 7) AS day",
        doctor_id,
    )

    before = await raw.fetchval("SELECT now()")
    rows = await _slots(raw, before.astimezone(EASTERN).date(), 2, doctor_id)
    after = await raw.fetchval("SELECT now()")

    first = min(row["slot_start"] for row in rows)
    assert first >= before + timedelta(hours=1)
    assert first < after + timedelta(hours=1, minutes=30)  # the very next half-hour slot
