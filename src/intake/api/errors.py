"""The response envelope and every error response, defined in one place.

Success is ``{"data": ..., "error": null}``; failure is ``{"data": null, "error":
{"code", "message", "details"}}``, where ``details`` lists field problems in the
same shape the voice agent's tools use. FastAPI's own error handlers are replaced,
so its raw error shapes never reach a client.
"""

from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from intake.core.models import FieldError, NotFound, PersistenceError, ValidationFailed

log = structlog.stdlib.get_logger("intake.api")

_CODES = {
    400: "BAD_REQUEST",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "PAYLOAD_TOO_LARGE",
    429: "RATE_LIMITED",
}
_MESSAGES = {
    400: "The request is malformed.",
    404: "Not found.",
    405: "This method isn't allowed on this path.",
}
_BODY_NOT_JSON = "The request body isn't valid JSON."
_BODY_NOT_AN_OBJECT = "The request body must be a JSON object, sent as application/json."


class ErrorBody(BaseModel):
    """What went wrong: a stable ``code``, a plain-English ``message`` and per-field ``details``."""

    code: str
    message: str
    details: list[FieldError]


class Envelope[T](BaseModel):
    """Every response body: ``data`` on success or ``error`` on failure, with the other null."""

    data: T | None
    error: ErrorBody | None


class ApiError(Exception):
    """An error response decided by a route, such as 400 for a malformed search term."""

    def __init__(
        self, status_code: int, code: str, message: str, details: Sequence[FieldError] = ()
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = list(details)


def ok(
    data: BaseModel | Sequence[BaseModel],
    *,
    status_code: int = 200,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """A success envelope around one response model or a list of them."""
    if isinstance(data, BaseModel):
        payload: Any = data.model_dump(mode="json")
    else:
        payload = [item.model_dump(mode="json") for item in data]
    return JSONResponse({"data": payload, "error": None}, status_code=status_code, headers=headers)


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Sequence[FieldError] = (),
    *,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """An error envelope."""
    error = ErrorBody(code=code, message=message, details=list(details))
    return JSONResponse(
        {"data": None, "error": error.model_dump(mode="json")},
        status_code=status_code,
        headers=headers,
    )


def bad_request(details: Sequence[FieldError]) -> ApiError:
    """400 for a malformed path id, query parameter or body; ``details`` says which."""
    if len(details) == 1:
        message = details[0].message
    else:
        message = f"{len(details)} parts of the request are malformed."
    return ApiError(400, "BAD_REQUEST", message, details)


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI entries for the error envelopes a route can return."""
    return {
        status: {"model": Envelope[None], "description": HTTPStatus(status).phrase}
        for status in status_codes
    }


def _describe(error: Mapping[str, Any]) -> FieldError:
    """Turn one of FastAPI's request errors into a detail, without echoing the input."""
    where, *rest = error["loc"]
    kind = error["type"]
    if where == "body":
        message = _BODY_NOT_JSON if kind == "json_invalid" else _BODY_NOT_AN_OBJECT
        return FieldError(field=None, code="invalid_body", message=message)
    name = str(rest[0]) if rest else str(where)
    return FieldError(
        field=name,
        code="invalid_parameter",
        message=f"{name} {_parameter_problem(kind, error.get('ctx') or {})}",
    )


def _parameter_problem(kind: str, ctx: Mapping[str, Any]) -> str:
    if kind.startswith("uuid"):
        return "must be a UUID."
    if kind.startswith("int"):
        return "must be a whole number."
    if kind == "less_than_equal":
        return f"must be at most {ctx['le']}."
    if kind == "greater_than_equal":
        return f"must be at least {ctx['ge']}."
    if kind == "enum":
        return f"must be one of {ctx['expected']}."
    return "is invalid."


def _invalid_fields_message(errors: Sequence[FieldError]) -> str:
    if all(error.field is None for error in errors):
        return errors[0].message
    return "1 field is invalid." if len(errors) == 1 else f"{len(errors)} fields are invalid."


async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, exc.details)


async def _http_error(_request: Request, exc: HTTPException) -> JSONResponse:
    code = _CODES.get(exc.status_code, "HTTP_ERROR")
    message = _MESSAGES.get(exc.status_code, str(exc.detail))
    return error_response(exc.status_code, code, message, headers=exc.headers)


async def _malformed_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    return await _api_error(request, bad_request([_describe(error) for error in exc.errors()]))


async def _validation_failed(_request: Request, exc: ValidationFailed) -> JSONResponse:
    return error_response(422, "VALIDATION_ERROR", _invalid_fields_message(exc.errors), exc.errors)


async def _not_found(_request: Request, exc: NotFound) -> JSONResponse:
    return error_response(404, "NOT_FOUND", f"{exc.what.capitalize()} not found.")


async def _database_error(_request: Request, exc: PersistenceError) -> JSONResponse:
    # The message is the failure's class name, never SQL or patient data.
    log.error("db.error", error=str(exc))
    return error_response(
        500, "DATABASE_ERROR", "The database isn't available right now. Please try again shortly."
    )


def install_error_handlers(app: FastAPI) -> None:
    """Answer every known failure with the error envelope and its status code."""
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _malformed_request)
    app.add_exception_handler(ValidationFailed, _validation_failed)
    app.add_exception_handler(NotFound, _not_found)
    app.add_exception_handler(PersistenceError, _database_error)
