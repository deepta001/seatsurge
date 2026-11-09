"""Turns typed DomainErrors into clean JSON error responses.

Clients get a stable machine-readable `error` code and a safe `message`, never
the exception's internal text (CLAUDE.md rule 10).
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.correlation import correlation_scope, new_correlation_id
from app.core.errors import DomainError

logger = logging.getLogger(__name__)


async def handle_domain_error(request: Request, error: Exception) -> JSONResponse:
    # Registered only for DomainError below; the check keeps mypy and readers sure.
    assert isinstance(error, DomainError)
    return JSONResponse(
        status_code=error.status_code,
        content={"error": error.code, "message": error.message},
        headers=error.headers,
    )


async def handle_validation_error(request: Request, error: Exception) -> JSONResponse:
    """422 that says WHICH field is wrong and why, without echoing what was sent.

    FastAPI's default includes the submitted value ("input"), so a too-short
    password would be sent straight back (and could end up in proxy logs).
    """
    assert isinstance(error, RequestValidationError)
    fields = [
        {"field": ".".join(str(part) for part in item["loc"]), "problem": item["msg"]}
        for item in error.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "message": "Some fields are missing or invalid.",
            "fields": fields,
        },
    )


async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
    """A bug or outage: a generic 500 with a correlation id; the details go to the logs only.

    The id lets a user's report ("it failed, id 3f2a...") be matched to the
    exact log entry, without the response ever revealing internals (rule 10).
    """
    # The request's own id (RequestContextMiddleware), so this line and the
    # request's other log lines share it. This handler runs outside that
    # middleware, so the id is bound again here for the log line.
    correlation_id = getattr(request.state, "correlation_id", None) or new_correlation_id()
    with correlation_scope(correlation_id):
        logger.error(
            "unexpected error %s on %s %s",
            correlation_id,
            request.method,
            request.url.path,
            exc_info=error,
        )
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "Something went wrong on our side. Please try again.",
            "correlation_id": correlation_id,
        },
        headers={"X-Correlation-ID": correlation_id},
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, handle_domain_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
