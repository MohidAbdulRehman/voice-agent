"""Response models: the shape and formats of every record the API returns.

Dates of birth render as ``MM/DD/YYYY`` and timestamps as ISO 8601 UTC with a
``Z`` suffix. Internal columns (a patient's ``source_call_id``, a call's room
name) are never exposed, and a caller's phone number is masked to its last four
digits: it's carrier metadata the caller never chose to give.
"""

from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, WithJsonSchema, field_validator

from intake.core.models import AppointmentStatus, BookedVia, CallStatus, Channel, Sex


def utc_timestamp(moment: datetime) -> str:
    """Render ``moment`` as ISO 8601 in UTC with a ``Z`` suffix, to the microsecond."""
    return moment.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def us_date(day: date) -> str:
    """Render ``day`` as ``MM/DD/YYYY``."""
    return day.strftime("%m/%d/%Y")


def mask_phone(number: str | None) -> str | None:
    """Keep only the last four digits of a phone number: ``***-***-0143``."""
    if number is None:
        return None
    digits = "".join(char for char in number if char in "0123456789")
    return f"***-***-{digits[-4:]}" if len(digits) >= 4 else "***"


Timestamp = Annotated[
    datetime,
    PlainSerializer(utc_timestamp, return_type=str),
    WithJsonSchema(
        {"type": "string", "format": "date-time", "examples": ["2026-09-24T15:04:05.123456Z"]}
    ),
]
UsDate = Annotated[
    date,
    PlainSerializer(us_date, return_type=str),
    WithJsonSchema(
        {"type": "string", "pattern": "^[0-9]{2}/[0-9]{2}/[0-9]{4}$", "examples": ["03/05/1990"]}
    ),
]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)


class PatientOut(_Out):
    """A registered patient."""

    patient_id: UUID
    first_name: str
    last_name: str
    date_of_birth: UsDate
    sex: Sex
    phone_number: str = Field(description="10 digits, e.g. 5125550100.")
    email: str | None
    address_line_1: str
    address_line_2: str | None
    city: str
    state: str = Field(description="USPS code, e.g. TX.")
    zip_code: str
    insurance_provider: str | None
    insurance_member_id: str | None
    preferred_language: str
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    created_at: Timestamp
    updated_at: Timestamp


class DeletedPatientOut(PatientOut):
    """A patient as returned by DELETE: the same record, now with ``deleted_at``."""

    deleted_at: Timestamp


class TranscriptEntryOut(_Out):
    """One spoken turn."""

    role: Literal["user", "assistant"]
    text: str
    at: Timestamp


class CallSummaryOut(_Out):
    """A call without its transcript, for lists."""

    call_id: UUID
    channel: Channel
    caller_number: str | None = Field(description="Masked to the last four digits.")
    status: CallStatus
    language: str
    patient_id: UUID | None
    summary: str | None
    end_reason: str | None
    started_at: Timestamp
    ended_at: Timestamp | None

    @field_validator("caller_number")
    @classmethod
    def _masked(cls, number: str | None) -> str | None:
        return mask_phone(number)


class CallOut(CallSummaryOut):
    """A call with its full transcript and the last data prepared during it."""

    final_payload: dict[str, Any] | None
    transcript: list[TranscriptEntryOut]


class AppointmentOut(_Out):
    """A booked (or cancelled) appointment."""

    appointment_id: UUID
    doctor_id: UUID
    doctor_name: str
    starts_at: Timestamp
    ends_at: Timestamp
    status: AppointmentStatus
    booked_via: BookedVia
    created_at: Timestamp


class DoctorOut(_Out):
    """A doctor who can be booked."""

    doctor_id: UUID
    full_name: str
    specialty: str
    languages: list[str]


class HealthOut(_Out):
    """The API is up and the database answers."""

    status: Literal["ok"]
    database: Literal["ok"]
    version: str


class DashboardConfigOut(_Out):
    """Public settings the dashboard shows."""

    clinic_name: str
    assistant_name: str
    phone_number: str | None = Field(description="The number to call, from PUBLIC_PHONE_NUMBER.")
    clinic_timezone: str
