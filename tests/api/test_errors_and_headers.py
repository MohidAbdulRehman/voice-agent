"""Cross-cutting behavior: failures stay in the envelope, headers, CORS and the request log."""

import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from intake.config import Settings
from intake.core.services import Services, build_services
from intake.logging import configure_logging
from tests.api.conftest import build_app, client_for
from tests.api.envelope import expect
from tests.cases import VALID_INPUT

ID = "00000000-0000-4000-8000-000000000001"
DATABASE_ROUTES = [
    ("GET", "/patients", None),
    ("POST", "/patients", VALID_INPUT),
    ("GET", f"/patients/{ID}", None),
    ("PUT", f"/patients/{ID}", {"city": "Dallas"}),
    ("DELETE", f"/patients/{ID}", None),
    ("GET", f"/patients/{ID}/calls", None),
    ("GET", f"/patients/{ID}/appointments", None),
    ("GET", "/calls", None),
    ("GET", f"/calls/{ID}", None),
    ("GET", "/doctors", None),
]


@pytest.mark.parametrize(("method", "path", "body"), DATABASE_ROUTES)
async def test_a_database_outage_is_a_500_database_error(
    unreachable: Services, tmp_path: Path, method: str, path: str, body: dict | None
):
    async with client_for(build_app(unreachable, tmp_path)) as client:
        error = expect(await client.request(method, path, json=body), 500)

    assert error["code"] == "DATABASE_ERROR"
    assert "SELECT" not in error["message"]


async def test_simulated_write_failures_are_500s_while_reads_work(
    engine: AsyncEngine, tmp_path: Path
):
    failing = build_services(engine, Settings(_env_file=None, simulate_db_failure=True))
    async with client_for(build_app(failing, tmp_path)) as client:
        error = expect(await client.post("/patients", json=VALID_INPUT), 500)
        assert expect(await client.get("/patients"), 200) == []

    assert error["code"] == "DATABASE_ERROR"


async def test_an_unexpected_error_is_a_500_internal_error(
    client: httpx.AsyncClient, services: Services, monkeypatch: pytest.MonkeyPatch
):
    async def broken() -> None:
        raise RuntimeError("bug")

    monkeypatch.setattr(services.scheduling, "doctors", broken)

    response = await client.get("/doctors")

    error = expect(response, 500)
    assert error == {
        "code": "INTERNAL_ERROR",
        "message": "Something went wrong on our side. Please try again.",
        "details": [],
    }
    assert response.headers["x-request-id"]
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_unknown_paths_are_not_found(client: httpx.AsyncClient):
    error = expect(await client.get("/nothing-here"), 404)

    assert error["code"] == "NOT_FOUND"


async def test_unsupported_methods_are_not_allowed(client: httpx.AsyncClient):
    response = await client.patch("/patients")

    error = expect(response, 405)
    assert error["code"] == "METHOD_NOT_ALLOWED"
    assert "GET" in response.headers["allow"]  # Starlette names the first matching route's methods


async def test_api_responses_carry_security_headers(client: httpx.AsyncClient):
    response = await client.get("/patients")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert "content-security-policy" not in response.headers  # that's for the dashboard
    assert len(response.headers["x-request-id"]) == 32


async def test_cors_allows_only_the_configured_origins(client: httpx.AsyncClient):
    preflight = {"access-control-request-method": "POST"}

    allowed = await client.options(
        "/patients", headers={**preflight, "origin": "http://localhost:5173"}
    )
    refused = await client.options(
        "/patients", headers={**preflight, "origin": "https://elsewhere.example.com"}
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-origin" not in refused.headers


@pytest.mark.usefixtures("restore_logging")
async def test_each_request_is_logged_once_without_its_query_or_body(
    client: httpx.AsyncClient, capsys: pytest.CaptureFixture[str]
):
    configure_logging("INFO")

    response = await client.post("/patients", json={**VALID_INPUT, "last_name": "Zyzzyva"})
    await client.get("/patients", params={"phone_number": "5125550100"})

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    server = [line for line in lines if line["logger"] != "httpx"]  # httpx is the test's client
    requests = [line for line in server if line["event"] == "http.request"]
    assert [(r["method"], r["path"], r["status"]) for r in requests] == [
        ("POST", "/patients", 201),
        ("GET", "/patients", 200),
    ]
    assert requests[0]["request_id"] == response.headers["x-request-id"]
    assert isinstance(requests[0]["duration_ms"], float)
    assert "Zyzzyva" not in json.dumps(server)
    assert "5125550100" not in json.dumps(server)


async def test_the_docs_are_served(client: httpx.AsyncClient):
    schema = (await client.get("/openapi.json")).json()
    docs = await client.get("/docs")

    assert {"/patients", "/patients/{patient_id}", "/calls", "/doctors", "/health"} <= set(
        schema["paths"]
    )
    assert docs.status_code == 200
    assert "text/html" in docs.headers["content-type"]
