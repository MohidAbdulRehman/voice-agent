"""/health, the dashboard's settings and static files, and the landing redirect."""

from importlib.metadata import version
from pathlib import Path

import httpx
import pytest

from intake.core.services import Services
from tests.api.conftest import build_app, client_for
from tests.api.envelope import expect


async def test_health_reports_the_database_and_version(client: httpx.AsyncClient):
    health = expect(await client.get("/health"), 200)

    assert health == {"status": "ok", "database": "ok", "version": version("patient-intake")}
    assert (await client.head("/health")).status_code == 200


async def test_health_is_503_when_the_database_is_down(unreachable: Services, tmp_path: Path):
    async with client_for(build_app(unreachable, tmp_path)) as client:
        error = expect(await client.get("/health"), 503)

    assert error["code"] == "SERVICE_UNAVAILABLE"


async def test_the_dashboard_config_is_public_settings_only(services: Services, tmp_path: Path):
    app = build_app(services, tmp_path, public_phone_number="+15125550100")
    async with client_for(app) as client:
        config = expect(await client.get("/dashboard/config"), 200)

    assert config == {
        "clinic_name": "Riverside Family Clinic",
        "assistant_name": "Maya",
        "phone_number": "+15125550100",
        "clinic_timezone": "America/New_York",
    }


@pytest.fixture
def built_dashboard(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text("<!doctype html><title>Dashboard</title>", "utf-8")
    return tmp_path


async def test_the_built_dashboard_is_served_with_a_csp(services: Services, built_dashboard: Path):
    async with client_for(build_app(services, built_dashboard)) as client:
        page = await client.get("/dashboard/")
        bare = await client.get("/dashboard")
        missing = await client.get("/dashboard/assets/missing.js")

    assert page.status_code == 200
    assert "<title>Dashboard</title>" in page.text
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert bare.status_code == 307
    assert bare.headers["location"].endswith("/dashboard/")
    assert expect(missing, 404)["code"] == "NOT_FOUND"


@pytest.mark.parametrize(("built", "target"), [(True, "/dashboard/"), (False, "/docs")])
async def test_the_bare_url_leads_somewhere_useful(
    services: Services, tmp_path: Path, built: bool, target: str
):
    if built:
        (tmp_path / "index.html").write_text("<!doctype html>", "utf-8")
    async with client_for(build_app(services, tmp_path)) as client:
        response = await client.get("/")

    assert response.status_code == 307
    assert response.headers["location"] == target
