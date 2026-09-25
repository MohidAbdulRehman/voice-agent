"""The Vercel deployment: entrypoint, region, bundle contents, dashboard build and headers."""

import importlib
import json
import re
import tomllib
from pathlib import Path

import app as vercel_entrypoint
from intake.api import main
from intake.api.middleware import DASHBOARD_CSP

ROOT = Path(__file__).resolve().parents[2]
VERCEL = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
VITE_CONFIG = (ROOT / "dashboard" / "vite.config.ts").read_text(encoding="utf-8")


def _names(requirements: list[str]) -> set[str]:
    """Package names from requirement strings like ``uvicorn[standard]>=0.53``."""
    return {re.match(r"[A-Za-z0-9._-]+", spec).group().lower() for spec in requirements}


def test_the_entrypoint_is_the_api_app():
    assert vercel_entrypoint.app is main.app
    assert set(VERCEL["functions"]) == {"app.py"}


def test_the_function_runs_next_to_the_database():
    assert VERCEL["regions"] == ["iad1"]  # Washington, D.C., beside Supabase us-east-1


def test_the_bundle_leaves_out_what_the_api_never_imports():
    excluded = VERCEL["functions"]["app.py"]["excludeFiles"]

    for path in ("src/intake/agent/**", "tests/**", "docs/**", "dashboard/**", "db/**"):
        assert path in excluded
    # The built dashboard stays: the function serves it if the CDN has no copy.
    assert "src/intake/api/static" not in excluded


def test_the_function_installs_only_api_dependencies():
    # Vercel runs `uv sync --no-dev`: extras (the server, the agent) never reach the bundle.
    names = _names(PYPROJECT["project"]["dependencies"])

    assert "fastapi" in names
    assert not {name for name in names if name.startswith(("uvicorn", "livekit", "onnxruntime"))}
    assert "uvicorn" in _names(PYPROJECT["project"]["optional-dependencies"]["server"])


def test_the_entrypoint_mounts_the_dashboard_the_build_command_writes(monkeypatch):
    # Vercel serves public/ only from committed files, so the build writes the dashboard
    # into the source tree, and the entrypoint mounts it from there: Vercel copies the
    # installed package before the build command runs, so it never has the files.
    mounted = []
    monkeypatch.setattr(main, "mount_dashboard", lambda app, path: mounted.append((app, path)))
    importlib.reload(vercel_entrypoint)

    assert VERCEL["buildCommand"].endswith("npm run build")
    assert 'outDir: "../src/intake/api/static"' in VITE_CONFIG
    assert mounted == [(main.app, ROOT / "src" / "intake" / "api" / "static")]


def test_vercel_copies_the_dashboard_mount_to_the_cdn_despite_the_middleware():
    # Without cdn = true, Vercel keeps mounts behind app-wide middleware in the function.
    assert PYPROJECT["tool"]["vercel"]["fastapi"]["static"] == {"cdn": True}


def test_a_daily_cron_keeps_the_free_database_awake():
    # /health runs SELECT 1; Supabase pauses a free project after a week without activity.
    assert VERCEL["crons"] == [{"path": "/health", "schedule": "0 12 * * *"}]


def test_the_bare_url_and_dashboard_path_lead_to_the_dashboard():
    assert {(r["source"], r["destination"], r["permanent"]) for r in VERCEL["redirects"]} == {
        ("/", "/dashboard/", False),
        ("/dashboard", "/dashboard/", False),
    }


def test_the_cdn_serves_the_dashboard_with_the_apis_security_headers():
    (rule,) = VERCEL["headers"]
    headers = {header["key"]: header["value"] for header in rule["headers"]}

    assert rule["source"] == "/dashboard/(.*)"
    assert headers == {
        "Content-Security-Policy": DASHBOARD_CSP,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }


def test_no_configuration_values_live_in_vercel_json():
    assert "env" not in VERCEL
    assert "build" not in VERCEL
