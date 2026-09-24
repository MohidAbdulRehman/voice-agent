"""PatientService against the test database."""

from datetime import date
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from intake.config import Settings
from intake.core.models import (
    CallStatus,
    DuplicateSourceCall,
    NotFound,
    PatientFilters,
    PersistenceError,
    ValidationFailed,
)
from intake.core.repository import Repository
from intake.core.services import CallService, PatientService, build_services
from intake.db.engine import make_engine
from tests.cases import VALID_INPUT
from tests.db.helpers import EASTERN, NOW

OTHER_PATIENT = {
    **VALID_INPUT,
    "first_name": "John",
    "last_name": "Smith",
    "date_of_birth": "01/02/1980",
    "phone_number": "212-555-0101",
}


async def test_create_normalizes_and_fills_defaults(patients: PatientService):
    patient = await patients.create({**VALID_INPUT, "last_name": "o'brien"})

    assert patient.last_name == "O'Brien"
    assert patient.phone_number == "5125550100"
    assert patient.date_of_birth == date(1990, 3, 5)
    assert patient.preferred_language == "English"
    assert patient.created_at == patient.updated_at
    assert patient.deleted_at is None
    assert await patients.get(patient.patient_id) == patient


async def test_invalid_data_writes_nothing(patients: PatientService):
    data = {**VALID_INPUT, "date_of_birth": "09/25/2026"}  # tomorrow at the clinic
    del data["last_name"]

    with pytest.raises(ValidationFailed) as excinfo:
        await patients.create(data)

    assert [(e.field, e.code) for e in excinfo.value.errors] == [
        ("last_name", "required"),
        ("date_of_birth", "in_future"),
    ]
    assert await patients.list_patients() == []


async def test_list_is_newest_first_and_pages(patients: PatientService):
    first = await patients.create(VALID_INPUT)
    second = await patients.create(OTHER_PATIENT)

    assert [p.patient_id for p in await patients.list_patients()] == [
        second.patient_id,
        first.patient_id,
    ]
    assert [p.patient_id for p in await patients.list_patients(limit=1, offset=1)] == [
        first.patient_id
    ]


@pytest.mark.parametrize(
    "filters",
    [
        PatientFilters(last_name="DOE"),
        PatientFilters(date_of_birth=date(1990, 3, 5)),
        PatientFilters(phone_number="5125550100"),
        PatientFilters(last_name="doe", date_of_birth=date(1990, 3, 5), phone_number="5125550100"),
    ],
)
async def test_filters_match_case_insensitively_and_combine(
    patients: PatientService, filters: PatientFilters
):
    jane = await patients.create(VALID_INPUT)
    await patients.create(OTHER_PATIENT)

    assert [p.patient_id for p in await patients.list_patients(filters)] == [jane.patient_id]


async def test_update_changes_only_the_fields_given(patients: PatientService):
    patient = await patients.create({**VALID_INPUT, "email": "jane@example.com"})

    updated = await patients.update(patient.patient_id, {"city": "Dallas", "email": None})

    assert (updated.city, updated.email) == ("Dallas", None)
    unchanged = {"city", "email", "updated_at"}
    assert updated.model_dump(exclude=unchanged) == patient.model_dump(exclude=unchanged)
    assert updated.updated_at > patient.updated_at


async def test_update_validates_before_writing(patients: PatientService):
    patient = await patients.create(VALID_INPUT)

    with pytest.raises(ValidationFailed):
        await patients.update(patient.patient_id, {"last_name": None})

    assert await patients.get(patient.patient_id) == patient


async def test_unknown_patients_are_not_found(patients: PatientService):
    with pytest.raises(NotFound, match="patient not found"):
        await patients.get(uuid4())
    with pytest.raises(NotFound, match="patient not found"):
        await patients.update(uuid4(), {"city": "Dallas"})
    with pytest.raises(NotFound, match="patient not found"):
        await patients.soft_delete(uuid4())


async def test_soft_delete_hides_the_patient_but_keeps_the_row(
    patients: PatientService, raw: asyncpg.Connection
):
    patient = await patients.create(VALID_INPUT)

    deleted = await patients.soft_delete(patient.patient_id)

    assert deleted.deleted_at is not None
    with pytest.raises(NotFound):
        await patients.get(patient.patient_id)
    with pytest.raises(NotFound):
        await patients.update(patient.patient_id, {"city": "Dallas"})
    with pytest.raises(NotFound):
        await patients.soft_delete(patient.patient_id)
    assert await patients.list_patients() == []
    assert await patients.find_by_phone("5125550100") == []
    assert await raw.fetchval(
        "SELECT deleted_at IS NOT NULL FROM patients WHERE patient_id = $1", patient.patient_id
    )


async def test_find_by_phone_normalizes_and_puts_the_latest_update_first(
    patients: PatientService,
):
    jane = await patients.create(VALID_INPUT)
    john = await patients.create({**VALID_INPUT, "first_name": "John"})
    await patients.update(jane.patient_id, {"city": "Dallas"})

    matches = await patients.find_by_phone("+1 (512) 555-0100")

    assert [p.patient_id for p in matches] == [jane.patient_id, john.patient_id]


@pytest.mark.parametrize(("number", "code"), [("555-0100", "invalid_phone"), ("  ", "required")])
async def test_find_by_phone_rejects_bad_numbers(patients: PatientService, number: str, code: str):
    with pytest.raises(ValidationFailed) as excinfo:
        await patients.find_by_phone(number)

    assert [(e.field, e.code) for e in excinfo.value.errors] == [("phone_number", code)]


async def test_registering_from_a_call_links_the_call_once(
    patients: PatientService, calls: CallService, raw: asyncpg.Connection
):
    call_id = await calls.start(room_name="room-1", channel="phone", caller_number="5125550100")

    patient = await patients.create(VALID_INPUT, call_id=call_id)

    call = await calls.get(call_id)
    assert (call.patient_id, call.status) == (patient.patient_id, CallStatus.REGISTERED)
    assert (
        await raw.fetchval(
            "SELECT source_call_id FROM patients WHERE patient_id = $1", patient.patient_id
        )
        == call_id
    )
    with pytest.raises(DuplicateSourceCall):
        await patients.create(OTHER_PATIENT, call_id=call_id)


async def test_updating_from_a_call_links_the_call(patients: PatientService, calls: CallService):
    patient = await patients.create(VALID_INPUT)
    call_id = await calls.start(room_name="room-1", channel="phone", caller_number="5125550100")

    await patients.update(patient.patient_id, {"city": "Dallas"}, call_id=call_id)

    call = await calls.get(call_id)
    assert (call.patient_id, call.status) == (patient.patient_id, CallStatus.UPDATED)


async def test_the_agent_may_name_the_state(patients: PatientService):
    patient = await patients.create({**VALID_INPUT, "state": "texas"}, accept_state_names=True)

    assert patient.state == "TX"


async def test_simulated_failure_blocks_patient_writes_only(engine: AsyncEngine):
    repository = Repository(engine, fail_patient_writes=True)
    patients = PatientService(repository, timezone=EASTERN, clock=lambda: NOW)
    calls = CallService(repository)
    call_id = await calls.start(room_name="room-1", channel="phone", caller_number=None)

    with pytest.raises(PersistenceError):
        await patients.create(VALID_INPUT, call_id=call_id)
    await calls.mark_failed(call_id)

    assert (await calls.get(call_id)).status == CallStatus.FAILED
    assert await patients.list_patients() == []


async def test_build_services_wires_the_simulation_flag(engine: AsyncEngine):
    services = build_services(engine, Settings(_env_file=None, simulate_db_failure=True))

    with pytest.raises(PersistenceError):
        await services.patients.create(VALID_INPUT)


async def test_an_unreachable_database_is_a_persistence_error():
    engine = make_engine("postgresql://postgres:postgres@127.0.0.1:1/intake_test")
    patients = PatientService(Repository(engine), timezone=EASTERN)
    try:
        with pytest.raises(PersistenceError):
            await patients.list_patients()
    finally:
        await engine.dispose()
