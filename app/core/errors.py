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
