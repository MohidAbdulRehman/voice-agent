"""Rate limits per client IP (slowapi): 120 requests a minute overall, 30 a minute for writes.

Every API route is decorated: ``limit_reads`` charges the shared overall counter,
and ``limit_writes`` charges both the writes counter and the overall one.
Decorators rather than slowapi's middleware, because the middleware finds a
route by scanning ``app.routes``, which no longer lists the routes of included
routers (FastAPI 0.141). Requests rejected before a handler runs (unknown paths,
malformed ids) aren't counted; they never reach the database. Counters live in
memory, which fits the single-process deployment. /health is never limited.
"""

import math
import time
from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from intake.api.errors import error_response

OVERALL_LIMIT = "120/minute"
WRITE_LIMIT = "30/minute"

limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")


def limit_reads[Route: Callable[..., Any]](route: Route) -> Route:
    """Count calls to ``route`` against the overall limit. It must take ``request: Request``."""
    return limiter.shared_limit(OVERALL_LIMIT, scope="overall")(route)


def limit_writes[Route: Callable[..., Any]](route: Route) -> Route:
    """Count calls to ``route`` against the write limit and the overall limit.

    It must take ``request: Request``. Both limits are checked before the route runs.
    """
    return limit_reads(limiter.shared_limit(WRITE_LIMIT, scope="writes")(route))


async def rate_limit_exceeded(request: Request, _exc: RateLimitExceeded) -> JSONResponse:
    """429 in the envelope, with ``Retry-After`` in seconds."""
    retry_after = _seconds_until_reset(request)
    return error_response(
        429,
        "RATE_LIMITED",
        f"Too many requests. Try again in {retry_after} seconds.",
        headers={"Retry-After": str(retry_after)},
    )


def _seconds_until_reset(request: Request) -> int:
    current = getattr(request.state, "view_rate_limit", None)
    if current is None:
        return 60
    item, keys = current
    reset_at, _remaining = limiter.limiter.get_window_stats(item, *keys)
    return max(1, math.ceil(reset_at - time.time()))
