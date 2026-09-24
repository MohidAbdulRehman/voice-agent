"""The FastAPI application: routes, middleware, error handlers and the dashboard.

``uvicorn intake.api.main:app`` serves it. ``create_app`` builds a fresh app, so
tests can hand it services wired to the test database.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from intake.api.errors import install_error_handlers
from intake.api.middleware import (
    BodySizeLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from intake.api.ratelimit import rate_limit_exceeded
from intake.api.routes import calls, dashboard, doctors, health, patients
from intake.config import Settings, get_settings
from intake.core.services import Services, build_services
from intake.db.engine import make_engine
from intake.logging import configure_logging

DASHBOARD_DIR = Path(__file__).resolve().parent / "static"  # written by `npm run build`

DESCRIPTION = """
Registers and looks up patients for {clinic}.

Every response is an envelope: `{{"data": ..., "error": null}}` on success, or
`{{"data": null, "error": {{"code", "message", "details"}}}}` on failure, where
`details` lists field problems as `{{"field", "code", "message"}}`.

- `date_of_birth` is `MM/DD/YYYY`; phone numbers may be in any US format and are
  stored as 10 digits; `state` is a USPS code such as `TX`.
- Timestamps are ISO 8601 in UTC with a `Z` suffix.
- Limits: 120 requests a minute per IP, of which 30 may be writes; bodies up to 32 KB.
- There is no authentication: a documented trade-off for this demo.
"""


def create_app(
    settings: Settings | None = None,
    *,
    services: Services | None = None,
    dashboard_dir: Path = DASHBOARD_DIR,
) -> FastAPI:
    """Build the app. Without ``services``, it connects to DATABASE_URL when it starts."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level)
        if services is not None:
            yield
            return
        if settings.database_url is None:
            raise RuntimeError("DATABASE_URL is not set")
        engine = make_engine(settings.database_url.get_secret_value())
        app.state.services = build_services(engine, settings)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title=f"{settings.clinic_name}: patient intake API",
        version=version("patient-intake"),
        description=DESCRIPTION.format(clinic=settings.clinic_name),
        lifespan=lifespan,
        redoc_url=None,
    )
    app.state.settings = settings
    if services is not None:
        app.state.services = services

    install_error_handlers(app)
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded)
    for module in (patients, calls, doctors, health, dashboard):
        app.include_router(module.router)
    app.state.dashboard = (dashboard_dir / "index.html").is_file()
    if app.state.dashboard:
        app.mount("/dashboard", StaticFiles(directory=dashboard_dir, html=True), name="dashboard")

    # Each middleware wraps the ones added before it: the last added runs first.
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
        expose_headers=["Location", "Retry-After", "X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    return app


app = create_app()
