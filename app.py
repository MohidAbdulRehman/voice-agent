"""Vercel entrypoint: the REST API (``intake.api.main``) runs as one Vercel Function.

Vercel's FastAPI preset looks for a top-level ``app`` here. Vercel installs the
intake package before the build command in vercel.json builds the dashboard, so
the built files sit in the source tree next to this file rather than in the
installed package; the dashboard is mounted from there. At build time Vercel
copies that mount to its CDN (``[tool.vercel.fastapi.static]`` in pyproject.toml).
"""

from pathlib import Path

from intake.api.main import app, mount_dashboard

mount_dashboard(app, Path(__file__).resolve().parent / "src" / "intake" / "api" / "static")

__all__ = ["app"]
