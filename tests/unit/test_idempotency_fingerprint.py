"""The request fingerprint changes when the request changes, and only then."""

from app.services.idempotency import request_fingerprint


def test_key_order_does_not_matter() -> None:
    assert request_fingerprint("POST /x", {"a": 1, "b": 2}) == request_fingerprint(
        "POST /x", {"b": 2, "a": 1}
    )


def test_a_different_body_or_route_changes_it() -> None:
    base = request_fingerprint("POST /events/1/holds", {"tier_id": 1, "quantity": 1})

    assert base != request_fingerprint("POST /events/1/holds", {"tier_id": 1, "quantity": 2})
    assert base != request_fingerprint("POST /events/2/holds", {"tier_id": 1, "quantity": 1})
