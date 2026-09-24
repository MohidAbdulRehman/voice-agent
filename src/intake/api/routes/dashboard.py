"""The dashboard's public settings, and a friendly landing redirect for the bare URL.

The dashboard itself is static files (built from dashboard/), mounted at
/dashboard by ``intake.api.main`` when they exist.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from intake.api.dependencies import SettingsDep
from intake.api.errors import Envelope, error_responses, ok
from intake.api.ratelimit import limit_reads
from intake.api.schemas import DashboardConfigOut

router = APIRouter(tags=["dashboard"])


@router.get(
    "/dashboard/config",
    response_model=Envelope[DashboardConfigOut],
    responses=error_responses(429),
)
@limit_reads
async def dashboard_config(request: Request, settings: SettingsDep) -> JSONResponse:
    """The clinic and assistant names, the number to call and the clinic's time zone."""
    return ok(
        DashboardConfigOut(
            clinic_name=settings.clinic_name,
            assistant_name=settings.agent_persona_name,
            phone_number=settings.public_phone_number,
            clinic_timezone=settings.clinic_timezone,
        )
    )


@router.get("/", include_in_schema=False)
async def home(request: Request) -> RedirectResponse:
    """Send someone opening the bare URL to the dashboard, or to the API docs if it isn't built."""
    return RedirectResponse("/dashboard/" if request.app.state.dashboard else "/docs")
