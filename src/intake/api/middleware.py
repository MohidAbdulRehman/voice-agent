"""ASGI middleware: request ids and access logs, security headers, and the body size limit.

Written as plain ASGI rather than ``BaseHTTPMiddleware``, so responses pass
through untouched and context bound here reaches every log line of the request.
"""

import time
from uuid import uuid4

import structlog
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from intake.api.errors import error_response

log = structlog.stdlib.get_logger("intake.api")

MAX_BODY_BYTES = 32 * 1024
TOO_LARGE = f"The request body is larger than {MAX_BODY_BYTES // 1024} KB."
DASHBOARD_CSP = "; ".join(
    (
        "default-src 'self'",
        "img-src 'self' data:",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    )
)


def _is_dashboard(path: str) -> bool:
    return path == "/dashboard" or path.startswith("/dashboard/")


class RequestContextMiddleware:
    """Give each request an id, log one line for it, and turn unexpected errors into a 500 envelope.

    The log line has the method, path, status and duration. It never has the
    query string or the body, which can hold patient data.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Run the request with its id bound to the log context; log it once it finishes."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex
        started = time.perf_counter()
        status = 500
        response_started = False

        async def send_with_id(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                MutableHeaders(scope=message).append("X-Request-ID", request_id)
            await send(message)

        with structlog.contextvars.bound_contextvars(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_id)
            except Exception:
                log.exception("http.unhandled_error", method=scope["method"], path=scope["path"])
                if response_started:
                    raise
                response = error_response(
                    500, "INTERNAL_ERROR", "Something went wrong on our side. Please try again."
                )
                await response(scope, receive, send_with_id)
            finally:
                write = log.error if status >= 500 else log.info
                write(
                    "http.request",
                    method=scope["method"],
                    path=scope["path"],
                    status=status,
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                )


class SecurityHeadersMiddleware:
    """Add ``nosniff`` and ``no-referrer`` everywhere, a CSP on the dashboard, and ``no-store`` on data.

    API responses carry patient data, so browsers and proxies must not cache them.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Add the headers as the response starts."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        dashboard = _is_dashboard(scope["path"])

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "no-referrer"
                if dashboard:
                    headers["Content-Security-Policy"] = DASHBOARD_CSP
                else:
                    headers.setdefault("Cache-Control", "no-store")
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodySizeLimitMiddleware:
    """Refuse request bodies over MAX_BODY_BYTES with 413.

    A declared ``Content-Length`` is checked before anything is read; a body sent
    without one is counted as it arrives.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass the request on, or answer 413 once its body is too large."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = _content_length(scope)
        if declared is not None and declared > self.max_bytes:
            await error_response(413, "PAYLOAD_TOO_LARGE", TOO_LARGE)(scope, receive, send)
            return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # FastAPI re-raises HTTPException from body reading; the envelope handler answers.
                    raise HTTPException(413, detail=TOO_LARGE)
            return message

        await self.app(scope, limited_receive, send)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope["headers"]:
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None
