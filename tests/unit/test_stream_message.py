"""parse_message turns raw stream fields into a StreamMessage, or raises PermanentError."""

import json

import pytest

from app.core.job_errors import PermanentError
from app.worker.consumer import StreamMessage, parse_message

GOOD = {
    "outbox_id": "7",
    "type": "order.placed",
    "aggregate_id": "order-1",
    "payload": json.dumps({"quantity": 2}),
}


def test_good_fields_are_parsed() -> None:
    assert parse_message("1-0", GOOD) == StreamMessage(
        entry_id="1-0",
        outbox_id=7,
        type="order.placed",
        aggregate_id="order-1",
        payload={"quantity": 2},
    )


@pytest.mark.parametrize(
    "broken",
    [
        {k: v for k, v in GOOD.items() if k != "outbox_id"},  # a field is missing
        {**GOOD, "outbox_id": "seven"},  # not a number
        {**GOOD, "payload": "{not json"},  # not JSON
        {**GOOD, "payload": "[1, 2]"},  # JSON, but not an object
    ],
)
def test_malformed_fields_are_a_permanent_error(broken: dict[str, str]) -> None:
    with pytest.raises(PermanentError):
        parse_message("1-0", broken)
