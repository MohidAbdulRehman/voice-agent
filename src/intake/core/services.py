"""Use cases shared by the REST API and the voice agent; every read and write goes through here.

Services validate with ``intake.core.validation``, then run SQL through the
repository in a single transaction. "Today" comes from an injectable clock in
the clinic's time zone, so tests can pin it.
"""

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncEngine

from intake.config import Settings
from intake.core.models import (
    Appointment,
    BookedVia,
    Call,
    CallStatus,
    Channel,
    Doctor,
    NotFound,
    Patient,
    PatientCreate,
    PatientFilters,
    PatientUpdate,
    PersistenceError,
    Slot,
    SlotTaken,
    TranscriptEntry,
)
from intake.core.repository import Repository
from intake.core.validation import (
    ValidationContext,
    clean_field,
    clinic_today,
    validate_filters,
    validate_new_patient,
    validate_patient_changes,
)

Clock = Callable[[], datetime]
DATABASE_CHECK_SECONDS = 5


def utc_now() -> datetime:
    """The current time, timezone-aware, in UTC."""
    return datetime.now(UTC)


class PatientService:
    """Registers, reads, updates and soft-deletes patients."""

    def __init__(
        self, repository: Repository, *, timezone: ZoneInfo, clock: Clock = utc_now
    ) -> None:
        self._repository = repository
        self._timezone = timezone
        self._clock = clock

    def _context(self, *, accept_state_names: bool = False) -> ValidationContext:
        today = clinic_today(self._clock(), self._timezone)
        return ValidationContext(today=today, accept_state_names=accept_state_names)

    def validate_new(
        self, data: Mapping[str, object], *, accept_state_names: bool = False
    ) -> PatientCreate:
        """Validate a complete new patient without saving it, e.g. to read it back first.

        Raises:
            ValidationFailed: listing every problem; missing fields are ``required``.
        """
        return validate_new_patient(data, self._context(accept_state_names=accept_state_names))

    def validate_changes(
        self, data: Mapping[str, object], *, accept_state_names: bool = False
    ) -> PatientUpdate:
        """Validate a partial update without saving it.

        Raises:
            ValidationFailed: listing every problem, or ``empty_update``.
        """
        return validate_patient_changes(data, self._context(accept_state_names=accept_state_names))

    async def create(
        self,
        data: Mapping[str, object],
        *,
        call_id: UUID | None = None,
        accept_state_names: bool = False,
    ) -> Patient:
        """Validate and insert a new patient.

        With ``call_id`` (the voice agent), the same transaction links the call
        to the patient and marks it ``registered``.

        Raises:
            ValidationFailed: the data broke a field rule; nothing was written.
            DuplicateSourceCall: this call already created a patient.
            PersistenceError: the database failed.
        """
        patient = validate_new_patient(data, self._context(accept_state_names=accept_state_names))
        async with self._repository.transaction() as tx:
            created = await tx.insert_patient(patient, source_call_id=call_id)
            if call_id is not None:
                await tx.update_call(
                    call_id, patient_id=created.patient_id, status=CallStatus.REGISTERED
                )
        return created

    async def get(self, patient_id: UUID) -> Patient:
        """Return an active patient.

        Raises:
            NotFound: no such patient, or it was soft-deleted.
        """
        async with self._repository.transaction() as tx:
            patient = await tx.get_patient(patient_id)
        if patient is None:
            raise NotFound("patient")
        return patient

    def filters(self, data: Mapping[str, object]) -> PatientFilters:
        """Turn raw search terms (``last_name``, ``date_of_birth``, ``phone_number``) into filters.

        Raises:
            ValidationFailed: a term isn't a valid value for its field, e.g. a
                date of birth that isn't MM/DD/YYYY.
        """
        return validate_filters(data, self._context())

    async def list_patients(
        self, filters: PatientFilters | None = None, *, limit: int = 50, offset: int = 0
    ) -> list[Patient]:
        """Active patients matching every filter given, newest first."""
        async with self._repository.transaction() as tx:
            return await tx.list_patients(filters or PatientFilters(), limit=limit, offset=offset)

    async def update(
        self,
        patient_id: UUID,
        data: Mapping[str, object],
        *,
        call_id: UUID | None = None,
        accept_state_names: bool = False,
    ) -> Patient:
        """Validate and apply a partial update; only the fields present change.

        With ``call_id``, the same transaction links the call and marks it ``updated``.

        Raises:
            ValidationFailed: the changes broke a field rule; nothing was written.
            NotFound: no such patient, or it was soft-deleted.
            PersistenceError: the database failed.
        """
        changes = validate_patient_changes(
            data, self._context(accept_state_names=accept_state_names)
        )
        async with self._repository.transaction() as tx:
            updated = await tx.update_patient(patient_id, changes.changes())
            if updated is None:
                raise NotFound("patient")
            if call_id is not None:
                await tx.update_call(call_id, patient_id=patient_id, status=CallStatus.UPDATED)
        return updated

    async def soft_delete(self, patient_id: UUID) -> Patient:
        """Set ``deleted_at``; the row stays, but lists and lookups no longer see it.

        Raises:
            NotFound: no such patient, or it was already deleted.
        """
        async with self._repository.transaction() as tx:
            deleted = await tx.soft_delete_patient(patient_id)
        if deleted is None:
            raise NotFound("patient")
        return deleted

    async def find_by_phone(self, phone_number: str) -> list[Patient]:
        """Active patients with this number (any format), most recently updated first.

        Raises:
            ValidationFailed: the number isn't a valid US phone number.
        """
        number = clean_field("phone_number", phone_number, self._context())
        async with self._repository.transaction() as tx:
            return await tx.patients_with_phone(str(number))


class CallService:
    """The ``calls`` row behind every conversation: lifecycle, transcript and reads."""

    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def _update(self, call_id: UUID, **values: object) -> None:
        async with self._repository.transaction() as tx:
            if not await tx.update_call(call_id, **values):
                raise NotFound("call")

    async def start(self, *, room_name: str, channel: Channel, caller_number: str | None) -> UUID:
        """Open the call (``in_progress``); a room that's dispatched again keeps its call."""
        async with self._repository.transaction() as tx:
            return await tx.start_call(
                room_name=room_name, channel=channel, caller_number=caller_number
            )

    async def save_payload(self, call_id: UUID, payload: Mapping[str, object]) -> None:
        """Keep the latest prepared data, so an abandoned or failed call still leaves a trace."""
        await self._update(call_id, final_payload=dict(payload))

    async def set_language(self, call_id: UUID, language: str) -> None:
        """Record the language the conversation switched to."""
        await self._update(call_id, language=language)

    async def mark_failed(self, call_id: UUID) -> None:
        """The caller confirmed but the write failed; staff follow up from ``final_payload``."""
        await self._update(call_id, status=CallStatus.FAILED)

    async def finish(
        self, call_id: UUID, *, end_reason: str, transcript: Sequence[TranscriptEntry]
    ) -> CallStatus:
        """Close the call with its transcript and return the settled status.

        Raises:
            NotFound: no such call.
        """
        async with self._repository.transaction() as tx:
            status = await tx.finish_call(call_id, end_reason=end_reason, transcript=transcript)
        if status is None:
            raise NotFound("call")
        return status

    async def save_summary(self, call_id: UUID, summary: str) -> None:
        """Attach the short post-call summary."""
        await self._update(call_id, summary=summary)

    async def get(self, call_id: UUID) -> Call:
        """Return one call with its transcript.

        Raises:
            NotFound: no such call.
        """
        async with self._repository.transaction() as tx:
            call = await tx.get_call(call_id)
        if call is None:
            raise NotFound("call")
        return call

    async def list_calls(
        self,
        *,
        status: CallStatus | None = None,
        patient_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Call]:
        """Calls, newest first; optionally one status, or one patient's calls."""
        async with self._repository.transaction() as tx:
            return await tx.list_calls(
                status=status, patient_id=patient_id, limit=limit, offset=offset
            )


class SchedulingService:
    """Doctors, free slots and bookings (mock data for the scheduling bonus)."""

    def __init__(
        self, repository: Repository, *, timezone: ZoneInfo, clock: Clock = utc_now
    ) -> None:
        self._repository = repository
        self._timezone = timezone
        self._clock = clock

    async def doctors(self) -> list[Doctor]:
        """Active doctors, by name."""
        async with self._repository.transaction() as tx:
            return await tx.active_doctors()

    async def open_slots(
        self, *, start: date | None = None, days: int = 14, doctor_id: UUID | None = None
    ) -> list[Slot]:
        """Free slots from ``start`` (default: today at the clinic), at least an hour away."""
        first_day = start or clinic_today(self._clock(), self._timezone)
        async with self._repository.transaction() as tx:
            return await tx.open_slots(
                start=first_day, days=days, timezone=self._timezone.key, doctor_id=doctor_id
            )

    async def book(
        self,
        *,
        patient_id: UUID,
        doctor_id: UUID,
        starts_at: datetime,
        booked_via: BookedVia,
        call_id: UUID | None = None,
    ) -> Appointment:
        """Book the slot that starts at ``starts_at`` with ``doctor_id``.

        Raises:
            SlotTaken: it isn't a free slot, or a concurrent booking won the race
                (the exclusion constraints decide), or the patient is busy then.
            PersistenceError: the database failed.
        """
        day = starts_at.astimezone(self._timezone).date()
        async with self._repository.transaction() as tx:
            slots = await tx.open_slots(
                start=day, days=1, timezone=self._timezone.key, doctor_id=doctor_id
            )
            slot = next((s for s in slots if s.starts_at == starts_at), None)
            if slot is None:
                raise SlotTaken
            return await tx.insert_appointment(
                patient_id=patient_id,
                doctor_id=doctor_id,
                starts_at=slot.starts_at,
                ends_at=slot.ends_at,
                booked_via=booked_via,
                call_id=call_id,
            )

    async def appointments_for(self, patient_id: UUID) -> list[Appointment]:
        """A patient's appointments, earliest first."""
        async with self._repository.transaction() as tx:
            return await tx.appointments_for_patient(patient_id)


class HealthService:
    """Whether the database answers, for ``/health`` and the uptime pinger."""

    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def database_ok(self) -> bool:
        """True if the database answers a trivial query within DATABASE_CHECK_SECONDS."""
        try:
            async with asyncio.timeout(DATABASE_CHECK_SECONDS):
                async with self._repository.transaction() as tx:
                    await tx.ping()
        except (PersistenceError, TimeoutError):
            return False
        return True


@dataclass(frozen=True)
class Services:
    """Every service, sharing one repository."""

    patients: PatientService
    calls: CallService
    scheduling: SchedulingService
    health: HealthService


def build_services(engine: AsyncEngine, settings: Settings, *, clock: Clock = utc_now) -> Services:
    """Wire the services from settings (clinic time zone, ``SIMULATE_DB_FAILURE``)."""
    repository = Repository(engine, fail_patient_writes=settings.simulate_db_failure)
    zone = settings.clinic_zone
    return Services(
        patients=PatientService(repository, timezone=zone, clock=clock),
        calls=CallService(repository),
        scheduling=SchedulingService(repository, timezone=zone, clock=clock),
        health=HealthService(repository),
    )
