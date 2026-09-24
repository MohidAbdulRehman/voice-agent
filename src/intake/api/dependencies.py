"""Route dependencies and shared parameter types."""

from typing import Annotated

from fastapi import Depends, Query, Request

from intake.config import Settings
from intake.core.services import Services


def get_services(request: Request) -> Services:
    """The services this app was built with."""
    return request.app.state.services


def get_settings(request: Request) -> Settings:
    """The settings this app was built with."""
    return request.app.state.settings


ServicesDep = Annotated[Services, Depends(get_services)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
Limit = Annotated[int, Query(ge=1, le=200, description="Page size, from 1 to 200.")]
Offset = Annotated[int, Query(ge=0, description="How many rows to skip.")]
