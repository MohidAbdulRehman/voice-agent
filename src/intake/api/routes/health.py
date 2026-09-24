"""/health: for Render's health check and the uptime pinger, which also keeps Supabase awake."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from intake.api.dependencies import ServicesDep
from intake.api.errors import Envelope, error_response, error_responses, ok
from intake.api.schemas import HealthOut

router = APIRouter(tags=["health"])


@router.head("/health", include_in_schema=False)  # some uptime pingers send HEAD
@router.get("/health", response_model=Envelope[HealthOut], responses=error_responses(503))
async def health(request: Request, services: ServicesDep) -> JSONResponse:
    """200 when the database answers ``SELECT 1``; 503 when it doesn't. Not rate limited."""
    if not await services.health.database_ok():
        return error_response(503, "SERVICE_UNAVAILABLE", "The database is unreachable.")
    return ok(HealthOut(status="ok", database="ok", version=request.app.version))
