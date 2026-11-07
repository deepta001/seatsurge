"""Creates the FastAPI application object that every API request goes through.

uvicorn imports `app` from here and serves it: `uv run uvicorn app.main:app`.
"""

from fastapi import FastAPI

from app.core.settings import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="A ticket booking backend that never oversells under heavy concurrency.",
    version="0.1.0",
)


# `async def` lets the server handle other requests while this one waits on
# slow things (databases, Redis). There's nothing to wait on yet, but every
# route will use it later.
@app.get("/")
async def read_root() -> dict[str, str]:
    """A hello endpoint that proves the server is up."""
    return {"message": "Hello from seatsurge"}
