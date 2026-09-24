"""Logs are JSON lines on stdout, with bound context and tracebacks."""

import json
import logging
from collections.abc import Iterator

import pytest
import structlog

from intake.logging import configure_logging


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    """Undo configure_logging, leaving pytest's own capture handlers alone."""
    root = logging.getLogger()
    level = root.level
    yield
    for handler in root.handlers[:]:
        if isinstance(handler.formatter, structlog.stdlib.ProcessorFormatter):
            root.removeHandler(handler)
    root.setLevel(level)
    structlog.reset_defaults()


def _only_line(capsys: pytest.CaptureFixture[str]) -> dict:
    (line,) = capsys.readouterr().out.splitlines()
    return json.loads(line)


def test_events_carry_level_logger_timestamp_and_context(capsys: pytest.CaptureFixture[str]):
    configure_logging("INFO")
    log = structlog.stdlib.get_logger("intake.test")

    with structlog.contextvars.bound_contextvars(call_id="call-1"):
        log.info("call.started", channel="phone")
    log.debug("below.the.level")

    record = _only_line(capsys)
    assert record["event"] == "call.started"
    assert record["level"] == "info"
    assert record["logger"] == "intake.test"
    assert record["call_id"] == "call-1"
    assert record["channel"] == "phone"
    assert record["timestamp"].endswith("Z")


def test_standard_library_records_are_json_too(capsys: pytest.CaptureFixture[str]):
    configure_logging("warning")
    library_logger = logging.getLogger("uvicorn.error")

    library_logger.warning("port %s is busy", 8000)
    library_logger.info("below the level")

    record = _only_line(capsys)
    assert record["event"] == "port 8000 is busy"
    assert record["level"] == "warning"
    assert record["logger"] == "uvicorn.error"


def test_exceptions_include_the_traceback(capsys: pytest.CaptureFixture[str]):
    configure_logging("INFO")

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        structlog.stdlib.get_logger("intake.test").exception("tool.failed")

    record = _only_line(capsys)
    assert record["level"] == "error"
    assert "RuntimeError: boom" in record["exception"]
