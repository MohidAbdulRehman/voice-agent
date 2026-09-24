"""/calls: the conversations the voice agent has had, newest first."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse

from intake.api.dependencies import Limit, Offset, ServicesDep
from intake.api.errors import Envelope, error_responses, ok
from intake.api.ratelimit import limit_reads
from intake.api.schemas import CallOut, CallSummaryOut
from intake.core.models import CallStatus

router = APIRouter(prefix="/calls", tags=["calls"])


@router.get(
    "",
    response_model=Envelope[list[CallSummaryOut]],
    responses=error_responses(400, 429, 500),
)
@limit_reads
async def list_calls(
    request: Request,
    services: ServicesDep,
    status: Annotated[CallStatus | None, Query(description="Only calls with this status.")] = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> JSONResponse:
    """Recent calls, newest first, without transcripts."""
    calls = await services.calls.list_calls(status=status, limit=limit, offset=offset)
    return ok([CallSummaryOut.model_validate(call) for call in calls])


@router.get(
    "/{call_id}",
    response_model=Envelope[CallOut],
    responses=error_responses(400, 404, 429, 500),
)
@limit_reads
async def get_call(
    request: Request,
    services: ServicesDep,
    call_id: Annotated[UUID, Path(description="The call's id.")],
) -> JSONResponse:
    """One call with its full transcript."""
    return ok(CallOut.model_validate(await services.calls.get(call_id)))
