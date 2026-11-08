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


class UserAlreadyExists(DomainError):
    status_code = 409
    code = "user_already_exists"
    message = "That email or username is already registered."
