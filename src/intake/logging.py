"""structlog logging: JSON lines to stdout for the API, LiveKit's handlers for the agent.

For the API, every line is one JSON object with ``event``, ``level``, ``logger``, a
UTC ISO 8601 ``timestamp`` and any context bound with ``structlog.contextvars``.
Standard-library records (uvicorn, SQLAlchemy) are rendered the same way, so one
parser reads every line. The agent's events carry the same fields (``call_id``
included), printed by LiveKit's command line, which already owns its output.
"""

import logging
import sys

import structlog
from structlog.typing import Processor


def configure_logging(level: str = "INFO") -> None:
    """Send structlog and standard-library logs to stdout as JSON lines at ``level``."""
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,  # lets tests reconfigure and capture logs
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # uvicorn gives its loggers their own plain-text handlers; route them through ours.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        library = logging.getLogger(name)
        library.handlers.clear()
        library.propagate = True
    # The API logs each request itself, without the query string (it can hold patient
    # data); uvicorn's access log would print it.
    logging.getLogger("uvicorn.access").disabled = True


def configure_agent_logging() -> None:
    """Send structlog events into standard logging, for LiveKit's own handlers to print.

    LiveKit's command line owns the agent's output: JSON lines in production and
    colored text in dev and console mode, at its ``--log-level``. Each event name
    becomes the record's message, and the bound fields (``call_id`` and the rest)
    become extra fields, which both formats print.
    """
    structlog.configure(
        processors=[structlog.contextvars.merge_contextvars, structlog.stdlib.render_to_log_kwargs],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
