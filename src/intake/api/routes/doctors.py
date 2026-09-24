"""/doctors: the mock doctors who can be booked."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from intake.api.dependencies import ServicesDep
from intake.api.errors import Envelope, error_responses, ok
from intake.api.ratelimit import limit_reads
from intake.api.schemas import DoctorOut

router = APIRouter(prefix="/doctors", tags=["scheduling"])


@router.get("", response_model=Envelope[list[DoctorOut]], responses=error_responses(429, 500))
@limit_reads
async def list_doctors(request: Request, services: ServicesDep) -> JSONResponse:
    """Active doctors by name, with specialty and spoken languages."""
    return ok([DoctorOut.model_validate(doctor) for doctor in await services.scheduling.doctors()])
