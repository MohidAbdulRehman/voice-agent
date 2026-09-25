"""Vercel entrypoint: the REST API (``intake.api.main``) runs as one Vercel Function.

Vercel's FastAPI preset looks for a top-level ``app`` here. The dashboard isn't
served by this function: the build command in vercel.json writes it to public/,
which Vercel serves from its CDN.
"""

from intake.api.main import app

__all__ = ["app"]
