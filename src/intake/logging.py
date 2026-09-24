"""structlog JSON logging to stdout, shared by the API and the agent.

Every line is one JSON object with ``event``, ``level``, ``logger``, a UTC ISO 8601
``timestamp`` and any context bound with ``structlog.contextvars`` (such as
``call_id``). Standard-library records (uvicorn, SQLAlchemy, LiveKit) are rendered
the same way, so one parser reads every line.
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
