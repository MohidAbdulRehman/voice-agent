"""/patients: list, read, register, update and soft-delete patients, plus their calls and appointments."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Path, Query, Request
from fastapi.responses import JSONResponse

from intake.api.dependencies import Limit, Offset, ServicesDep
from intake.api.errors import Envelope, bad_request, error_responses, ok
from intake.api.ratelimit import limit_reads, limit_writes
from intake.api.schemas import AppointmentOut, CallOut, DeletedPatientOut, PatientOut
from intake.core.models import ValidationFailed

router = APIRouter(prefix="/patients", tags=["patients"])

_REQUIRED_ONLY = {
    "first_name": "Jane",
    "last_name": "Doe",
    "date_of_birth": "03/05/1990",
    "sex": "Female",
    "phone_number": "(512) 555-0100",
    "address_line_1": "1 Main St",
    "city": "Austin",
    "state": "TX",
    "zip_code": "78701",
}
_EVERY_FIELD = {
    **_REQUIRED_ONLY,
    "email": "jane.doe@example.com",
    "address_line_2": "Apt 4",
    "insurance_provider": "Aetna",
    "insurance_member_id": "W123456789",
    "preferred_language": "Spanish",
    "emergency_contact_name": "John Doe",
    "emergency_contact_phone": "512-555-0101",
}

NewPatient = Annotated[
    dict[str, Any],
    Body(
        description=(
            "Every required field, plus any optional ones, as strings. Unknown and"
            " read-only fields are rejected with 422."
        ),
        openapi_examples={
            "required": {"summary": "Required fields only", "value": _REQUIRED_ONLY},
            "every_field": {"summary": "Every field", "value": _EVERY_FIELD},
        },
    ),
]
PatientChanges = Annotated[
    dict[str, Any],
    Body(
        description=(
            "Only the fields to change. null clears an optional field; required fields"
            ' and preferred_language can\'t be cleared (send "English" to reset the language).'
        ),
        openapi_examples={
            "move": {"summary": "Change the city", "value": {"city": "Dallas"}},
            "clear": {"summary": "Clear the email", "value": {"email": None}},
        },
    ),
]
PatientId = Annotated[UUID, Path(description="The patient's id.")]


@router.get(
    "",
    response_model=Envelope[list[PatientOut]],
    responses=error_responses(400, 429, 500),
)
@limit_reads
async def list_patients(
    request: Request,
    services: ServicesDep,
    last_name: Annotated[
        str | None, Query(description="Case-insensitive exact match, e.g. doe.")
    ] = None,
    date_of_birth: Annotated[str | None, Query(description="MM/DD/YYYY, e.g. 03/05/1990.")] = None,
    phone_number: Annotated[
        str | None, Query(description="Any US format, e.g. (512) 555-0100.")
    ] = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> JSONResponse:
    """List patients, newest first. Filters are validated like the fields they search and combine with AND."""
    terms = {"last_name": last_name, "date_of_birth": date_of_birth, "phone_number": phone_number}
    try:
        filters = services.patients.filters(terms)
    except ValidationFailed as exc:
        raise bad_request(exc.errors) from None
    patients = await services.patients.list_patients(filters, limit=limit, offset=offset)
    return ok([PatientOut.model_validate(patient) for patient in patients])


@router.post(
    "",
    status_code=201,
    response_model=Envelope[PatientOut],
    responses=error_responses(400, 413, 422, 429, 500),
)
@limit_writes
async def create_patient(
    request: Request, services: ServicesDep, fields: NewPatient
) -> JSONResponse:
    """Register a patient. Returns the stored record and its URL in ``Location``."""
    patient = await services.patients.create(fields)
    return ok(
        PatientOut.model_validate(patient),
        status_code=201,
        headers={"Location": f"/patients/{patient.patient_id}"},
    )


@router.get(
    "/{patient_id}",
    response_model=Envelope[PatientOut],
    responses=error_responses(400, 404, 429, 500),
)
@limit_reads
async def get_patient(
    request: Request, services: ServicesDep, patient_id: PatientId
) -> JSONResponse:
    """Read one patient; soft-deleted patients are not found."""
    return ok(PatientOut.model_validate(await services.patients.get(patient_id)))


@router.put(
    "/{patient_id}",
    response_model=Envelope[PatientOut],
    responses=error_responses(400, 404, 413, 422, 429, 500),
)
@limit_writes
async def update_patient(
    request: Request, services: ServicesDep, patient_id: PatientId, fields: PatientChanges
) -> JSONResponse:
    """Change only the fields given. Returns the whole updated record."""
    return ok(PatientOut.model_validate(await services.patients.update(patient_id, fields)))


@router.delete(
    "/{patient_id}",
    response_model=Envelope[DeletedPatientOut],
    responses=error_responses(400, 404, 429, 500),
)
@limit_writes
async def delete_patient(
    request: Request, services: ServicesDep, patient_id: PatientId
) -> JSONResponse:
    """Soft-delete: set ``deleted_at`` and hide the patient. The row is kept."""
    return ok(DeletedPatientOut.model_validate(await services.patients.soft_delete(patient_id)))


@router.get(
    "/{patient_id}/calls",
    response_model=Envelope[list[CallOut]],
    responses=error_responses(400, 404, 429, 500),
)
@limit_reads
async def list_patient_calls(
    request: Request, services: ServicesDep, patient_id: PatientId
) -> JSONResponse:
    """The patient's calls, newest first, with summaries and transcripts."""
    await services.patients.get(patient_id)
    calls = await services.calls.list_calls(patient_id=patient_id)
    return ok([CallOut.model_validate(call) for call in calls])


@router.get(
    "/{patient_id}/appointments",
    response_model=Envelope[list[AppointmentOut]],
    responses=error_responses(400, 404, 429, 500),
)
@limit_reads
async def list_patient_appointments(
    request: Request, services: ServicesDep, patient_id: PatientId
) -> JSONResponse:
    """The patient's appointments, earliest first, with the doctor's name."""
    await services.patients.get(patient_id)
    appointments = await services.scheduling.appointments_for(patient_id)
    return ok([AppointmentOut.model_validate(appointment) for appointment in appointments])
