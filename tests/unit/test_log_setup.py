"""JSON log lines and the correlation id (S8.2b)."""

import io
import json
import logging
from collections.abc import Iterator

import pytest

from app.core.correlation import (
    correlation_scope,
    current_correlation_id,
    usable_correlation_id,
)
from app.core.log_setup import LogFormat, build_formatter, configure_logging


def render(record_logger: logging.Logger, log_format: LogFormat = "json") -> io.StringIO:
    """Send this logger's records through our formatter into a string buffer."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(build_formatter(log_format))
    record_logger.addHandler(handler)
    return stream


@pytest.fixture
def demo_logger() -> Iterator[logging.Logger]:
    logger = logging.getLogger("tests.demo")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    yield logger
    logger.handlers.clear()
    logger.propagate = True


def test_a_log_line_is_one_json_object_with_the_correlation_id(
    demo_logger: logging.Logger,
) -> None:
    stream = render(demo_logger)
    with correlation_scope("req-12345678", outbox_id=7):
        demo_logger.info("order %s placed", "o-1", extra={"status": 202})
    demo_logger.info("outside any request")

    first, second = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert first["event"] == "order o-1 placed"
    assert first["correlation_id"] == "req-12345678"
    assert first["outbox_id"] == 7
    assert first["status"] == 202  # from extra={...}
    assert first["level"] == "info"
    assert first["logger"] == "tests.demo"
    assert first["timestamp"].endswith("Z")  # UTC
    assert "correlation_id" not in second  # the scope ended


def test_an_exception_is_logged_as_a_field_on_the_same_line(demo_logger: logging.Logger) -> None:
    stream = render(demo_logger)
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        demo_logger.exception("it failed")
    [line] = stream.getvalue().splitlines()  # one line, traceback included
    entry = json.loads(line)
    assert "RuntimeError: boom" in entry["exception"]


def test_console_format_is_readable_text(demo_logger: logging.Logger) -> None:
    stream = render(demo_logger, "console")
    with correlation_scope("req-12345678"):
        demo_logger.info("hello")
    assert "hello" in stream.getvalue() and "correlation_id=req-12345678" in stream.getvalue()


@pytest.mark.parametrize(
    ("incoming", "kept"),
    [
        ("0f8e2c1d9a7b4c3e8d6f5a4b3c2d1e0f", True),  # nginx's $request_id
        ("my-trace-0001", True),
        (None, False),
        ("short", False),  # under 8 characters
        ('x" , "admin": true', False),  # would inject text into JSON log lines
        ("line\nbreak-1234", False),
        ("a" * 65, False),
    ],
)
def test_only_safe_incoming_ids_are_kept(incoming: str | None, kept: bool) -> None:
    result = usable_correlation_id(incoming)
    assert (result == incoming) is kept
    assert len(result) >= 8


def test_no_id_outside_a_scope_and_scopes_restore_the_outer_id() -> None:
    assert current_correlation_id() is None
    with correlation_scope("outer-0001"):
        with correlation_scope("inner-0001"):
            assert current_correlation_id() == "inner-0001"
        assert current_correlation_id() == "outer-0001"
    assert current_correlation_id() is None


def test_configuring_twice_does_not_duplicate_lines() -> None:
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        configure_logging("json")
        configure_logging("json")
        ours = [h for h in root.handlers if isinstance(h.formatter, type(build_formatter("json")))]
        assert len(ours) == 1
        # uvicorn writes access lines only if this logger has handlers (its own
        # or, by propagating, the root's): ours replace them, so it must have none.
        assert not logging.getLogger("uvicorn.access").hasHandlers()
        assert logging.getLogger("uvicorn.error").propagate is True
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
