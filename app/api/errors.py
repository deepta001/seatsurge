"""Turns typed DomainErrors into clean JSON error responses.

Clients get a stable machine-readable `error` code and a safe `message`, never
the exception's internal text (CLAUDE.md rule 10).
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.errors import DomainError


async def handle_domain_error(request: Request, error: Exception) -> JSONResponse:
    # Registered only for DomainError below; the check keeps mypy and readers sure.
    assert isinstance(error, DomainError)
    return JSONResponse(
        status_code=error.status_code,
        content={"error": error.code, "message": error.message},
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, handle_domain_error)
