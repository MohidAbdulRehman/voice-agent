"""SchedulingService: doctors, free slots and bookings."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from intake.core.models import AppointmentStatus, SlotTaken
from intake.core.services import SchedulingService
from tests.db.helpers import AVERY, EASTERN, LUIS, REED, RUIZ, SHAH, at, upcoming

pytestmark = pytest.mark.usefixtures("seeded")


async def test_doctors_are_listed_by_name(scheduling: SchedulingService):
    doctors = await scheduling.doctors()

    assert [(d.full_name, d.languages) for d in doctors] == [
        ("Dr. Elena Ruiz", ("English", "Spanish")),
        ("Dr. Marcus Reed", ("English",)),
        ("Dr. Priya Shah", ("English",)),
    ]


async def test_open_slots_start_today_and_at_least_an_hour_out(scheduling: SchedulingService):
    slots = await scheduling.open_slots(days=14)

    assert slots
    assert slots[0].starts_at >= datetime.now(UTC) + timedelta(minutes=59)
    assert slots == sorted(slots, key=lambda s: (s.starts_at, s.doctor_name))
    assert {s.doctor_name for s in slots} == {"Dr. Elena Ruiz", "Dr. Marcus Reed", "Dr. Priya Shah"}


async def test_open_slots_for_one_doctor(scheduling: SchedulingService):
    slots = await scheduling.open_slots(start=upcoming(1), days=1, doctor_id=RUIZ)

    assert len(slots) == 14
    assert {s.doctor_id for s in slots} == {RUIZ}


async def test_booking_a_free_slot(scheduling: SchedulingService):
    nine = at(upcoming(0), 9)

    appointment = await scheduling.book(
        patient_id=AVERY, doctor_id=SHAH, starts_at=nine, booked_via="voice_agent"
    )

    assert (appointment.doctor_name, appointment.starts_at, appointment.ends_at) == (
        "Dr. Priya Shah",
        nine,
        nine + timedelta(minutes=30),
    )
    assert appointment.status == AppointmentStatus.SCHEDULED
    assert await scheduling.appointments_for(AVERY) == [appointment]
    booked_slots = await scheduling.open_slots(start=nine.date(), days=1, doctor_id=SHAH)
    assert nine not in {s.starts_at for s in booked_slots}


async def test_a_booked_slot_is_taken(scheduling: SchedulingService):
    nine = at(upcoming(0), 9)
    await scheduling.book(patient_id=AVERY, doctor_id=SHAH, starts_at=nine, booked_via="api")

    with pytest.raises(SlotTaken):
        await scheduling.book(patient_id=LUIS, doctor_id=SHAH, starts_at=nine, booked_via="api")


async def test_a_patient_cannot_see_two_doctors_at_once(scheduling: SchedulingService):
    nine = at(upcoming(0), 9)
    await scheduling.book(patient_id=AVERY, doctor_id=SHAH, starts_at=nine, booked_via="api")

    with pytest.raises(SlotTaken):
        await scheduling.book(patient_id=AVERY, doctor_id=REED, starts_at=nine, booked_via="api")


@pytest.mark.parametrize(
    "starts_at",
    [
        at(upcoming(0), 9, 10),  # not on the half hour
        at(upcoming(0), 12),  # lunch
        at(upcoming(5), 10),  # Saturday
        datetime.now(EASTERN) - timedelta(days=1),  # the past
    ],
    ids=["off-grid", "lunch", "saturday", "past"],
)
async def test_times_that_are_not_slots_are_refused(
    scheduling: SchedulingService, starts_at: datetime
):
    with pytest.raises(SlotTaken):
        await scheduling.book(
            patient_id=AVERY, doctor_id=SHAH, starts_at=starts_at, booked_via="api"
        )


async def test_when_two_callers_race_for_a_slot_exactly_one_wins(scheduling: SchedulingService):
    nine = at(upcoming(0), 9)

    results = await asyncio.gather(
        scheduling.book(patient_id=AVERY, doctor_id=SHAH, starts_at=nine, booked_via="voice_agent"),
        scheduling.book(patient_id=LUIS, doctor_id=SHAH, starts_at=nine, booked_via="voice_agent"),
        return_exceptions=True,
    )

    assert sorted(type(result).__name__ for result in results) == ["Appointment", "SlotTaken"]
