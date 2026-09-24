"""Parameterized SQL for every table, one transaction at a time.

Statements are built with SQLAlchemy Core, never with string formatting. Database
failures become ``PersistenceError``; the constraint violations the domain cares
about become ``DuplicateSourceCall`` and ``SlotTaken``. db/migrations/0001_init.sql
is the source of truth for the schema; the tables below only describe columns
for building queries (tests/db/test_schema.py checks that they match).
"""

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import date, datetime
from uuid import UUID

import asyncpg
from sqlalchemy import (
    Boolean,
    Column,
    ColumnElement,
    Date,
    DateTime,
    FetchedValue,
    MetaData,
    Row,
    Table,
    Text,
    Uuid,
    case,
    func,
    insert,
    literal,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from intake.core.models import (
    Appointment,
    AppointmentStatus,
    BookedVia,
    Call,
    CallStatus,
    Channel,
    Doctor,
    DuplicateSourceCall,
    Patient,
    PatientCreate,
    PatientFilters,
    PersistenceError,
    Sex,
    Slot,
    SlotTaken,
    TranscriptEntry,
)

metadata = MetaData()

_sex_type = ENUM(*(s.value for s in Sex), name="sex_type", create_type=False)
_call_status = ENUM(*(s.value for s in CallStatus), name="call_status", create_type=False)
_appointment_status = ENUM(
    *(s.value for s in AppointmentStatus), name="appointment_status", create_type=False
)


def _timestamp(name: str) -> Column:
    return Column(name, DateTime(timezone=True))


def _generated_id(name: str) -> Column:
    # The database fills it in (DEFAULT gen_random_uuid()).
    return Column(name, Uuid, primary_key=True, server_default=FetchedValue())


patients = Table(
    "patients",
    metadata,
    _generated_id("patient_id"),
    Column("first_name", Text),
    Column("last_name", Text),
    Column("date_of_birth", Date),
    Column("sex", _sex_type),
    Column("phone_number", Text),
    Column("email", Text),
    Column("address_line_1", Text),
    Column("address_line_2", Text),
    Column("city", Text),
    Column("state", Text),
    Column("zip_code", Text),
    Column("insurance_provider", Text),
    Column("insurance_member_id", Text),
    Column("preferred_language", Text),
    Column("emergency_contact_name", Text),
    Column("emergency_contact_phone", Text),
    Column("source_call_id", Uuid),
    _timestamp("created_at"),
    _timestamp("updated_at"),
    _timestamp("deleted_at"),
)

calls = Table(
    "calls",
    metadata,
    _generated_id("call_id"),
    Column("room_name", Text),
    Column("channel", Text),
    Column("caller_number", Text),
    Column("status", _call_status),
    Column("language", Text),
    Column("patient_id", Uuid),
    Column("final_payload", JSONB(none_as_null=True)),
    Column("transcript", JSONB),
    Column("summary", Text),
    Column("end_reason", Text),
    _timestamp("started_at"),
    _timestamp("ended_at"),
)

doctors = Table(
    "doctors",
    metadata,
    _generated_id("doctor_id"),
    Column("full_name", Text),
    Column("specialty", Text),
    Column("languages", ARRAY(Text)),
    Column("is_active", Boolean),
)

appointments = Table(
    "appointments",
    metadata,
    _generated_id("appointment_id"),
    Column("patient_id", Uuid),
    Column("doctor_id", Uuid),
    _timestamp("starts_at"),
    _timestamp("ends_at"),
    Column("status", _appointment_status),
    Column("booked_via", Text),
    Column("call_id", Uuid),
    _timestamp("created_at"),
    _timestamp("updated_at"),
)

# source_call_id is internal bookkeeping and never leaves the repository.
_PATIENT_COLUMNS = tuple(c for c in patients.c if c.name != "source_call_id")
_APPOINTMENT_COLUMNS = (
    appointments.c.appointment_id,
    appointments.c.patient_id,
    appointments.c.doctor_id,
    doctors.c.full_name.label("doctor_name"),
    appointments.c.starts_at,
    appointments.c.ends_at,
    appointments.c.status,
    appointments.c.booked_via,
    appointments.c.call_id,
    appointments.c.created_at,
)
_DOUBLE_BOOKING = frozenset({"no_doctor_double_booking", "no_patient_double_booking"})
_OPEN_SLOTS = text(
    "SELECT s.slot_doctor_id AS doctor_id, d.full_name AS doctor_name,"
    " s.slot_start AS starts_at, s.slot_end AS ends_at"
    " FROM available_slots(CAST(:start AS date), CAST(:days AS integer),"
    " CAST(:doctor_id AS uuid), CAST(:timezone AS text)) AS s"
    " JOIN doctors AS d ON d.doctor_id = s.slot_doctor_id"
    " ORDER BY s.slot_start, d.full_name"
)
# Anything that means "the database didn't do it". Connection failures arrive
# from asyncpg or the socket layer without SQLAlchemy wrapping them.
_DATABASE_ERRORS = (SQLAlchemyError, OSError, asyncpg.PostgresError, asyncpg.InterfaceError)


def _violated_constraint(exc: IntegrityError) -> str | None:
    return getattr(getattr(exc.orig, "__cause__", None), "constraint_name", None)


def _patient(row: Row) -> Patient:
    return Patient.model_validate(row._mapping)


def _call(row: Row) -> Call:
    return Call.model_validate(row._mapping)


def _appointment(row: Row) -> Appointment:
    return Appointment.model_validate(row._mapping)


class Repository:
    """Opens transactions and turns database failures into ``PersistenceError``.

    With ``fail_patient_writes`` (``SIMULATE_DB_FAILURE=true``), every write to
    ``patients`` fails, while call bookkeeping keeps working, so tests and demos
    can show the caller hearing an apology and the call being marked failed.
    """

    def __init__(self, engine: AsyncEngine, *, fail_patient_writes: bool = False) -> None:
        self._engine = engine
        self._fail_patient_writes = fail_patient_writes

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator["Transaction"]:
        """Run the block in one transaction, committed only if the block succeeds."""
        try:
            async with self._engine.begin() as conn:
                yield Transaction(conn, fail_patient_writes=self._fail_patient_writes)
        except _DATABASE_ERRORS as exc:
            raise PersistenceError(type(exc).__name__) from exc


class Transaction:
    """The statements available inside one transaction."""

    def __init__(self, conn: AsyncConnection, *, fail_patient_writes: bool) -> None:
        self._conn = conn
        self._fail_patient_writes = fail_patient_writes

    def _check_patient_write(self) -> None:
        if self._fail_patient_writes:
            raise PersistenceError("simulated failure (SIMULATE_DB_FAILURE=true)")

    # --- patients -------------------------------------------------------------

    async def insert_patient(
        self, patient: PatientCreate, *, source_call_id: UUID | None
    ) -> Patient:
        """Insert a validated patient, optionally tagged with the call that created it."""
        self._check_patient_write()
        statement = (
            insert(patients)
            .values(**patient.model_dump(), source_call_id=source_call_id)
            .returning(*_PATIENT_COLUMNS)
        )
        try:
            result = await self._conn.execute(statement)
        except IntegrityError as exc:
            if _violated_constraint(exc) == "patients_source_call_id_key":
                raise DuplicateSourceCall from exc
            raise
        return _patient(result.one())

    async def get_patient(self, patient_id: UUID) -> Patient | None:
        """Return an active (not soft-deleted) patient."""
        statement = select(*_PATIENT_COLUMNS).where(
            patients.c.patient_id == patient_id, patients.c.deleted_at.is_(None)
        )
        row = (await self._conn.execute(statement)).one_or_none()
        return None if row is None else _patient(row)

    async def list_patients(
        self, filters: PatientFilters, *, limit: int, offset: int
    ) -> list[Patient]:
        """Active patients matching every filter given, newest first."""
        statement = select(*_PATIENT_COLUMNS).where(patients.c.deleted_at.is_(None))
        if filters.last_name is not None:
            statement = statement.where(
                func.lower(patients.c.last_name) == func.lower(filters.last_name)
            )
        if filters.date_of_birth is not None:
            statement = statement.where(patients.c.date_of_birth == filters.date_of_birth)
        if filters.phone_number is not None:
            statement = statement.where(patients.c.phone_number == filters.phone_number)
        statement = (
            statement.order_by(patients.c.created_at.desc(), patients.c.patient_id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_patient(row) for row in await self._conn.execute(statement)]

    async def patients_with_phone(self, phone_number: str) -> list[Patient]:
        """Active patients with this 10-digit number, most recently updated first."""
        statement = (
            select(*_PATIENT_COLUMNS)
            .where(patients.c.phone_number == phone_number, patients.c.deleted_at.is_(None))
            .order_by(patients.c.updated_at.desc())
        )
        return [_patient(row) for row in await self._conn.execute(statement)]

    async def update_patient(
        self, patient_id: UUID, changes: Mapping[str, object]
    ) -> Patient | None:
        """Apply validated changes to an active patient; None if there's no such patient."""
        self._check_patient_write()
        statement = (
            update(patients)
            .where(patients.c.patient_id == patient_id, patients.c.deleted_at.is_(None))
            .values(**changes)
            .returning(*_PATIENT_COLUMNS)
        )
        row = (await self._conn.execute(statement)).one_or_none()
        return None if row is None else _patient(row)

    async def soft_delete_patient(self, patient_id: UUID) -> Patient | None:
        """Set ``deleted_at`` on an active patient; None if there's no such patient."""
        self._check_patient_write()
        statement = (
            update(patients)
            .where(patients.c.patient_id == patient_id, patients.c.deleted_at.is_(None))
            .values(deleted_at=func.now())
            .returning(*_PATIENT_COLUMNS)
        )
        row = (await self._conn.execute(statement)).one_or_none()
        return None if row is None else _patient(row)

    # --- calls ----------------------------------------------------------------

    async def start_call(
        self, *, room_name: str, channel: Channel, caller_number: str | None
    ) -> UUID:
        """Create the calls row, or return the existing one if the room was dispatched again."""
        statement = pg_insert(calls).values(
            room_name=room_name, channel=channel, caller_number=caller_number
        )
        statement = statement.on_conflict_do_update(
            index_elements=[calls.c.room_name], set_={"room_name": statement.excluded.room_name}
        ).returning(calls.c.call_id)
        return (await self._conn.execute(statement)).scalar_one()

    async def update_call(self, call_id: UUID, **values: object) -> bool:
        """Set columns on a call; False if there's no such call."""
        statement = (
            update(calls)
            .where(calls.c.call_id == call_id)
            .values(**values)
            .returning(calls.c.call_id)
        )
        return (await self._conn.execute(statement)).one_or_none() is not None

    async def finish_call(
        self, call_id: UUID, *, end_reason: str, transcript: Sequence[TranscriptEntry]
    ) -> CallStatus | None:
        """Close a call and settle its status; None if there's no such call.

        A committed or failed call keeps its status. Otherwise it's ``abandoned``
        when data was collected, and ``no_action`` when nothing was.
        """
        settled = [CallStatus.REGISTERED, CallStatus.UPDATED, CallStatus.FAILED]
        status = case(
            (calls.c.status.in_(settled), calls.c.status),
            (calls.c.final_payload.is_not(None), literal(CallStatus.ABANDONED, _call_status)),
            else_=literal(CallStatus.NO_ACTION, _call_status),
        )
        statement = (
            update(calls)
            .where(calls.c.call_id == call_id)
            .values(
                status=status,
                end_reason=end_reason,
                transcript=[entry.model_dump(mode="json") for entry in transcript],
                ended_at=func.now(),
            )
            .returning(calls.c.status)
        )
        status_value = (await self._conn.execute(statement)).scalar_one_or_none()
        return None if status_value is None else CallStatus(status_value)

    async def get_call(self, call_id: UUID) -> Call | None:
        """Return one call with its full transcript."""
        row = (
            await self._conn.execute(select(calls).where(calls.c.call_id == call_id))
        ).one_or_none()
        return None if row is None else _call(row)

    async def list_calls(
        self, *, status: CallStatus | None, patient_id: UUID | None, limit: int, offset: int
    ) -> list[Call]:
        """Calls, newest first, optionally only one status or one patient's."""
        statement = select(calls)
        if status is not None:
            statement = statement.where(calls.c.status == status)
        if patient_id is not None:
            statement = statement.where(calls.c.patient_id == patient_id)
        statement = (
            statement.order_by(calls.c.started_at.desc(), calls.c.call_id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_call(row) for row in await self._conn.execute(statement)]

    # --- scheduling -----------------------------------------------------------

    async def active_doctors(self) -> list[Doctor]:
        """Doctors who can be booked, by name."""
        statement = (
            select(
                doctors.c.doctor_id, doctors.c.full_name, doctors.c.specialty, doctors.c.languages
            )
            .where(doctors.c.is_active)
            .order_by(doctors.c.full_name)
        )
        return [Doctor.model_validate(row._mapping) for row in await self._conn.execute(statement)]

    async def open_slots(
        self, *, start: date, days: int, timezone: str, doctor_id: UUID | None
    ) -> list[Slot]:
        """Free slots from ``available_slots()``, earliest first."""
        parameters = {"start": start, "days": days, "doctor_id": doctor_id, "timezone": timezone}
        result = await self._conn.execute(_OPEN_SLOTS, parameters)
        return [Slot.model_validate(row._mapping) for row in result]

    async def insert_appointment(
        self,
        *,
        patient_id: UUID,
        doctor_id: UUID,
        starts_at: datetime,
        ends_at: datetime,
        booked_via: BookedVia,
        call_id: UUID | None,
    ) -> Appointment:
        """Book a slot; the exclusion constraints reject double bookings."""
        statement = (
            insert(appointments)
            .values(
                patient_id=patient_id,
                doctor_id=doctor_id,
                starts_at=starts_at,
                ends_at=ends_at,
                booked_via=booked_via,
                call_id=call_id,
            )
            .returning(appointments.c.appointment_id)
        )
        try:
            appointment_id = (await self._conn.execute(statement)).scalar_one()
        except IntegrityError as exc:
            if _violated_constraint(exc) in _DOUBLE_BOOKING:
                raise SlotTaken from exc
            raise
        return (await self._appointments(appointments.c.appointment_id == appointment_id))[0]

    async def appointments_for_patient(self, patient_id: UUID) -> list[Appointment]:
        """A patient's appointments, earliest first."""
        return await self._appointments(appointments.c.patient_id == patient_id)

    async def _appointments(self, condition: ColumnElement[bool]) -> list[Appointment]:
        statement = (
            select(*_APPOINTMENT_COLUMNS)
            .join(doctors, doctors.c.doctor_id == appointments.c.doctor_id)
            .where(condition)
            .order_by(appointments.c.starts_at)
        )
        return [_appointment(row) for row in await self._conn.execute(statement)]
