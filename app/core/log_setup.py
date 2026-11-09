"""Structured logs: one JSON object per line, with the correlation id (S8.2b).

The code keeps using Python's standard `logging.getLogger(__name__)`.
Only the OUTPUT changes: structlog's formatter turns each record into JSON
and adds the time, level, logger name, any `extra={...}` fields and the
current correlation id. JSON lines can be searched and filtered by field
("all lines with correlation_id=abc"), which plain text can't do reliably.
"""

import logging
import sys
from typing import Literal

import structlog

LogFormat = Literal["json", "console"]


def build_formatter(log_format: LogFormat) -> structlog.stdlib.ProcessorFormatter:
    # Steps applied to every standard-library log record, in order.
    shared_steps: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,  # adds correlation_id (and friends)
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.ExtraAdder(),  # logger.info("...", extra={"status": 200})
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    final_steps: list[structlog.typing.Processor]
    if log_format == "json":
        # The traceback becomes a text field, then the whole entry one JSON line.
        final_steps = [structlog.processors.format_exc_info, structlog.processors.JSONRenderer()]
    else:
        final_steps = [structlog.dev.ConsoleRenderer(colors=False)]  # readable when developing
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_steps,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *final_steps],
    )


def configure_logging(log_format: LogFormat = "json", level: int = logging.INFO) -> None:
    """Send every log record, ours and uvicorn's, to stdout in one format. Safe to call twice."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(build_formatter(log_format))

    root = logging.getLogger()
    root.handlers.clear()  # replace, never stack (a second call must not double every line)
    root.addHandler(handler)
    root.setLevel(level)

    # uvicorn installs its own plain-text handlers at startup; route its
    # records through ours instead.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    # uvicorn's access log stays OFF: the API writes its own access line, with
    # the correlation id (app/api/request_context.py). uvicorn writes access
    # lines whenever this logger "has handlers", and a propagating logger
    # borrows the root's, so it must not propagate (found live in S8.2b).
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
