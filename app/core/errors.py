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
