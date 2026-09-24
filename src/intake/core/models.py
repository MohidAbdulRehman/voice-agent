"""Domain models and errors shared by the REST API and the voice agent.

``PatientCreate`` and ``PatientUpdate`` only ever hold data that passed
``intake.core.validation``; ``Patient``, ``Call``, ``Doctor``, ``Slot`` and
``Appointment`` are stored records.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

Channel = Literal["phone", "web", "console"]
BookedVia = Literal["voice_agent", "api", "dashboard"]


class Sex(StrEnum):
    """The ``sex_type`` enum."""

    MALE = "Male"
    FEMALE = "Female"
    OTHER = "Other"
    DECLINE = "Decline to Answer"


class CallStatus(StrEnum):
    """The ``call_status`` enum."""

    IN_PROGRESS = "in_progress"
    REGISTERED = "registered"
    UPDATED = "updated"
    NO_ACTION = "no_action"
    ABANDONED = "abandoned"
    FAILED = "failed"


class AppointmentStatus(StrEnum):
    """The ``appointment_status`` enum."""

    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class FieldError(_Frozen):
    """One validation problem; the same shape in API responses and agent tool results."""

    field: str | None
    code: str
    message: str


class PatientCreate(_Frozen):
    """A validated new patient, ready to insert."""

    first_name: str
    last_name: str
    date_of_birth: date
    sex: Sex
    phone_number: str
    email: str | None = None
    address_line_1: str
    address_line_2: str | None = None
    city: str
    state: str
    zip_code: str
    insurance_provider: str | None = None
    insurance_member_id: str | None = None
    preferred_language: str = "English"
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None


class PatientUpdate(_Frozen):
    """Validated changes. Only fields in ``model_fields_set`` change; ``None`` clears one."""

    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    sex: Sex | None = None
    phone_number: str | None = None
    email: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    insurance_provider: str | None = None
    insurance_member_id: str | None = None
    preferred_language: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None

    def changes(self) -> dict[str, Any]:
        """The fields to write, keyed by column name."""
        return self.model_dump(exclude_unset=True)


class Patient(PatientCreate):
    """A stored patient. ``deleted_at`` is set only on soft-deleted rows."""

    patient_id: UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class PatientFilters(_Frozen):
    """Optional filters for listing patients, combined with AND."""

    last_name: str | None = None
    date_of_birth: date | None = None
    phone_number: str | None = None


class TranscriptEntry(_Frozen):
    """One spoken turn in a call transcript."""

    role: Literal["user", "assistant"]
    text: str
    at: datetime


class Call(_Frozen):
    """One conversation: phone, web playground or console."""

    call_id: UUID
    room_name: str
    channel: Channel
    caller_number: str | None
    status: CallStatus
    language: str
    patient_id: UUID | None
    final_payload: dict[str, Any] | None
    transcript: list[TranscriptEntry]
    summary: str | None
    end_reason: str | None
    started_at: datetime
    ended_at: datetime | None


class Doctor(_Frozen):
    """An active doctor who can be booked."""

    doctor_id: UUID
    full_name: str
    specialty: str
    languages: tuple[str, ...]


class Slot(_Frozen):
    """A free appointment slot."""

    doctor_id: UUID
    doctor_name: str
    starts_at: datetime
    ends_at: datetime


class Appointment(_Frozen):
    """A booked (or cancelled) appointment, with the doctor's name."""

    appointment_id: UUID
    patient_id: UUID
    doctor_id: UUID
    doctor_name: str
    starts_at: datetime
    ends_at: datetime
    status: AppointmentStatus
    booked_via: BookedVia
    call_id: UUID | None
    created_at: datetime


class ValidationFailed(Exception):
    """Input broke one or more field rules; ``errors`` lists every problem."""

    def __init__(self, errors: list[FieldError]) -> None:
        super().__init__(f"{len(errors)} invalid field(s)")
        self.errors = errors


class NotFound(Exception):
    """The record doesn't exist, or it was soft-deleted. ``what`` names the kind of record."""

    def __init__(self, what: str = "record") -> None:
        super().__init__(f"{what} not found")
        self.what = what


class PersistenceError(Exception):
    """The database was unreachable or rejected the write."""


class DuplicateSourceCall(Exception):
    """This call already created a patient; a call can create at most one."""


class SlotTaken(Exception):
    """The slot isn't free: someone else booked it, it isn't a real slot, or the patient is busy."""
