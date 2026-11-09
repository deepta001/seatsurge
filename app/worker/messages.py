"""The message the worker reads from `stream:orders`, and how raw stream fields become one."""

import json
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from app.core.correlation import correlation_scope
from app.core.job_errors import PermanentError


@dataclass(frozen=True)
class StreamMessage:
    """One outbox event as read from the stream, with its fields checked and parsed."""

    entry_id: str  # Redis's id for this copy of the message
    outbox_id: int  # the outbox row it came from (the same for duplicates)
    type: str
    aggregate_id: str
    payload: dict[str, Any]


Handler = Callable[[StreamMessage], Awaitable[None]]


def parse_message(entry_id: str, fields: Mapping[str, str]) -> StreamMessage:
    """Turn raw stream fields into a StreamMessage. Bad data can never become good: permanent."""
    try:
        payload = json.loads(fields["payload"])
        if not isinstance(payload, dict):
            raise ValueError("payload is not a JSON object")
        return StreamMessage(
            entry_id=entry_id,
            outbox_id=int(fields["outbox_id"]),
            type=fields["type"],
            aggregate_id=fields["aggregate_id"],
            payload=payload,
        )
    except (KeyError, ValueError) as error:  # json.JSONDecodeError is a ValueError
        raise PermanentError(f"malformed stream message {entry_id}: {error!r}") from error


@contextmanager
def message_scope(entry_id: str, fields: Mapping[str, str]) -> Iterator[None]:
    """Log lines while handling this entry carry its request's correlation id (S8.2b).

    Read straight from the raw fields, so even a message too broken to parse
    is logged with whatever id it has. Older messages simply have none.
    """
    with correlation_scope(
        fields.get("correlation_id"), stream_entry=entry_id, outbox_id=fields.get("outbox_id")
    ):
        yield
