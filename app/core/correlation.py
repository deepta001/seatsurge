"""The correlation id: one id per request, carried API -> outbox row -> worker (S8.2b).

It is stored in a context variable (via structlog), which follows the code
of ONE request or ONE message even while many run at once on the event
loop. Every log line written meanwhile gets it automatically, so searching
the logs for one id shows that request's whole journey.
"""

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import structlog

KEY = "correlation_id"
# Ids we accept from outside (nginx's $request_id, or a client in local dev).
# Anything else is replaced, so nobody can write arbitrary text into our logs.
VALID_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def usable_correlation_id(candidate: str | None) -> str:
    """The incoming id if it looks safe, otherwise a fresh one."""
    if candidate and VALID_ID.match(candidate):
        return candidate
    return new_correlation_id()


def current_correlation_id() -> str | None:
    """The id of the request or message being handled right now (None outside one)."""
    value = structlog.contextvars.get_contextvars().get(KEY)
    return value if isinstance(value, str) else None


@contextmanager
def correlation_scope(correlation_id: str | None, **extra: object) -> Iterator[None]:
    """Everything logged inside this block carries the id (and `extra`), then it is removed."""
    if correlation_id is None:
        with structlog.contextvars.bound_contextvars(**extra):
            yield
        return
    with structlog.contextvars.bound_contextvars(**{KEY: correlation_id}, **extra):
        yield
