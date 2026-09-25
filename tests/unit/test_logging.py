"""Logs are JSON lines on stdout, with bound context and tracebacks."""

import json
import logging

import pytest
import structlog

from intake.logging import configure_agent_logging, configure_logging

pytestmark = pytest.mark.usefixtures("restore_logging")


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


def test_uvicorn_logs_are_json_and_its_access_log_is_off(capsys: pytest.CaptureFixture[str]):
    uvicorn_error = logging.getLogger("uvicorn.error")
    uvicorn_error.addHandler(logging.StreamHandler())  # as uvicorn's own log config does
    uvicorn_error.propagate = False
    configure_logging("INFO")

    uvicorn_error.info("Application startup complete.")
    logging.getLogger("uvicorn.access").info('GET /patients?last_name=Doe "200"')

    record = _only_line(capsys)
    assert record["event"] == "Application startup complete."
    assert record["logger"] == "uvicorn.error"


def test_agent_events_reach_livekits_handlers_as_records_with_their_fields(
    caplog: pytest.LogCaptureFixture,
):
    configure_agent_logging()
    caplog.set_level(logging.INFO, logger="intake.agent")
    log = structlog.stdlib.get_logger("intake.agent")

    with structlog.contextvars.bound_contextvars(call_id="call-1"):
        log.info("tool.called", tool="start_over", status="cleared")
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            log.exception("tool.failed", tool="commit_record")

    called, failed = caplog.records
    assert called.getMessage() == "tool.called"
    assert (called.tool, called.status, called.call_id) == ("start_over", "cleared", "call-1")
    assert failed.levelname == "ERROR"
    assert failed.exc_info is not None  # the handler formats the traceback
    assert (failed.tool, failed.call_id) == ("commit_record", "call-1")


def test_exceptions_include_the_traceback(capsys: pytest.CaptureFixture[str]):
    configure_logging("INFO")

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        structlog.stdlib.get_logger("intake.test").exception("tool.failed")

    record = _only_line(capsys)
    assert record["level"] == "error"
    assert "RuntimeError: boom" in record["exception"]
