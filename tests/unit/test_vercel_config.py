"""The Vercel deployment: entrypoint, region, bundle contents, dashboard build and headers."""

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
DASHBOARD_SCRIPTS = json.loads((ROOT / "dashboard" / "package.json").read_text(encoding="utf-8"))[
    "scripts"
]


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


def test_the_function_installs_only_api_dependencies():
    # Vercel runs `uv sync --no-dev`: extras (the server, the agent) never reach the bundle.
    names = _names(PYPROJECT["project"]["dependencies"])

    assert "fastapi" in names
    assert not {name for name in names if name.startswith(("uvicorn", "livekit", "onnxruntime"))}
    assert "uvicorn" in _names(PYPROJECT["project"]["optional-dependencies"]["server"])


def test_the_build_writes_the_dashboard_to_the_cdn_folder():
    assert "npm run build:vercel" in VERCEL["buildCommand"]
    assert "--outDir ../public/dashboard" in DASHBOARD_SCRIPTS["build:vercel"]


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
