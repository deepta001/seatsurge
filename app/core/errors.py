"""Typed errors for expected failures (CLAUDE.md rule 9).

Code raises a specific class, and app/api/errors.py turns it into a clean HTTP
response. Nobody ever matches on error message text, and clients never see
raw exception details (rule 10).
"""


class DomainError(Exception):
    """Base class for expected business errors. Subclasses set the response details."""

    status_code: int = 400
    code: str = "bad_request"
    message: str = "The request could not be completed."
    # Extra response headers, e.g. WWW-Authenticate on a 401.
    headers: dict[str, str] | None = None


class UserAlreadyExists(DomainError):
    status_code = 409
    code = "user_already_exists"
    message = "That email or username is already registered."


class InvalidCredentials(DomainError):
    # One message for "no such email" and "wrong password", so login can't be
    # used to discover which emails have accounts.
    status_code = 401
    code = "invalid_credentials"
    message = "Email or password is incorrect."


class NotAuthenticated(DomainError):
    """Missing, expired, tampered or otherwise invalid access token."""

    status_code = 401
    code = "not_authenticated"
    message = "A valid access token is required."
    # The standard HTTP hint telling clients which kind of credentials to send.
    headers = {"WWW-Authenticate": "Bearer"}


class Forbidden(DomainError):
    """Logged in, but not allowed to do this (e.g. a USER calling an admin route)."""

    status_code = 403
    code = "forbidden"
    message = "You don't have permission to do that."


class EventNotFound(DomainError):
    status_code = 404
    code = "event_not_found"
    message = "No event with that id."


class InvalidEventStatusChange(DomainError):
    # Events only move forward: DRAFT -> PUBLISHED -> CANCELLED.
    status_code = 409
    code = "invalid_status_change"
    message = "An event can't move to that status from its current one."


class EventNotDeletable(DomainError):
    # Once published, tickets may exist, so an event can only be cancelled.
    status_code = 409
    code = "event_not_deletable"
    message = "Only DRAFT events can be deleted; cancel a published event instead."


class TierNotFound(DomainError):
    status_code = 404
    code = "tier_not_found"
    message = "No tier with that id for this event."


class EventNotOnSale(DomainError):
    # Cancelled, or already started.
    status_code = 409
    code = "event_not_on_sale"
    message = "This event isn't on sale."


class SeatingNotSupported(DomainError):
    # Reserved-seating events use per-seat holds (Phase D).
    status_code = 422
    code = "seating_not_supported"
    message = "This event uses reserved seating; choose specific seats instead."


class SoldOut(DomainError):
    status_code = 409
    code = "sold_out"
    message = "Not enough seats left in this tier."


class HoldLimitExceeded(DomainError):
    status_code = 409
    code = "hold_limit_exceeded"
    message = "You're already holding the most seats allowed for this event."


class InventoryNotReady(DomainError):
    """The Redis seat counter is missing. Never treated as zero (CLAUDE.md rule 4)."""

    status_code = 503
    code = "inventory_not_ready"
    message = "Seat availability is being prepared. Please try again shortly."
    headers = {"Retry-After": "1"}


class IdempotencyKeyReused(DomainError):
    # Same Idempotency-Key, different request: almost certainly a client bug.
    status_code = 422
    code = "idempotency_key_reused"
    message = "This Idempotency-Key was already used for a different request."


class RequestInProgress(DomainError):
    # A retry arrived while the first request with this key is still running.
    status_code = 409
    code = "request_in_progress"
    message = "A request with this Idempotency-Key is still being processed."
    headers = {"Retry-After": "1"}


class HoldNotFound(DomainError):
    # Also used for someone else's hold, so hold ids can't be probed.
    status_code = 404
    code = "hold_not_found"
    message = "No hold with that id."


class InvalidPaymentToken(DomainError):
    status_code = 422
    code = "invalid_payment_token"
    message = "That payment token isn't valid."


class PaymentDeclined(DomainError):
    # 402 Payment Required: the standard status for "the payment didn't go through".
    status_code = 402
    code = "payment_declined"
    message = "The payment was declined."


class PaymentUnavailable(DomainError):
    """The payment provider couldn't be reached. Temporary: retrying may work."""

    status_code = 503
    code = "payment_unavailable"
    message = "Payments are temporarily unavailable. Please try again shortly."
    headers = {"Retry-After": "2"}


class HoldExpired(DomainError):
    # 410 Gone: it existed, but it's no longer available.
    status_code = 410
    code = "hold_expired"
    message = "This hold has expired or was released."


class ConfirmInProgress(DomainError):
    status_code = 409
    code = "confirm_in_progress"
    message = "This hold is already being confirmed."
    headers = {"Retry-After": "1"}


class PurchaseLimitExceeded(DomainError):
    status_code = 409
    code = "purchase_limit_exceeded"
    message = "You've reached the most tickets allowed for this event."


class OrderNotFound(DomainError):
    # Also for someone else's order, so ids can't be probed (rule 1).
    status_code = 404
    code = "order_not_found"
    message = "No such order."


class OrderNotCancellable(DomainError):
    status_code = 409
    code = "order_not_cancellable"
    message = "Only an order with issued tickets can be cancelled."


class NoSeatMap(DomainError):
    status_code = 422
    code = "no_seat_map"
    message = "This event is general admission: it has no individual seats."


class InvalidSeats(DomainError):
    status_code = 422
    code = "invalid_seats"
    message = "Choose seats that belong to this event, all in the same tier."


class SeatTaken(DomainError):
    # Someone else holds or bought at least one of the chosen seats; nothing was held.
    status_code = 409
    code = "seat_taken"
    message = "One or more of those seats is no longer available."


class SeatPurchaseNotAvailable(DomainError):
    # Holding specific seats works (S6.2); buying them arrives in S6.2b.
    status_code = 422
    code = "seat_purchase_not_available"
    message = "Buying reserved seats is not available yet."
