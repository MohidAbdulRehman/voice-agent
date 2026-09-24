"""The envelope every response follows (docs/specs/api.md), asserted on every API call."""

import re
from typing import Any

import httpx

TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z")
US_DATE = re.compile(r"[0-9]{2}/[0-9]{2}/[0-9]{4}")


def expect(response: httpx.Response, status: int) -> Any:
    """Assert the status and the envelope; return ``data`` on success or ``error`` on failure."""
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    assert set(body) == {"data", "error"}
    if status >= 400:
        assert body["data"] is None
        error = body["error"]
        assert set(error) == {"code", "message", "details"}
        assert error["code"].isupper()
        assert error["message"]
        for detail in error["details"]:
            assert set(detail) == {"field", "code", "message"}
        return error
    assert body["error"] is None
    _assert_formats(body["data"])
    return body["data"]


def _assert_formats(value: Any) -> None:
    """Timestamps are ISO 8601 UTC with Z; dates of birth are MM/DD/YYYY."""
    if isinstance(value, list):
        for item in value:
            _assert_formats(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if item is None:
                continue
            if key.endswith("_at") or key == "at":
                assert TIMESTAMP.fullmatch(item), (key, item)
            elif key == "date_of_birth":
                assert US_DATE.fullmatch(item), (key, item)
            else:
                _assert_formats(item)
