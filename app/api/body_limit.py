"""Middleware that refuses request bodies over a size limit with 413, before the app sees them.

Without it, a client could send a 50 MB "hold request" and the server would
read and parse all of it before validation said no. This middleware reads
the body itself, stops as soon as it passes the limit (even for chunked
uploads that declare no length), and only then hands it to FastAPI.
"""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def _too_large() -> JSONResponse:
    return JSONResponse(
        status_code=413,
        content={"error": "payload_too_large", "message": "The request body is too large."},
    )


class BodySizeLimitMiddleware:
    """A raw ASGI middleware: it sits between the server (uvicorn) and FastAPI."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 1. Cheap check: refuse a declared size that's already too big (or garbage).
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > self.max_bytes):
            await _too_large()(scope, receive, send)
            return

        # 2. Read the body ourselves, counting bytes as they arrive, because a
        #    client can lie about its size or (chunked) not declare one at all.
        #    Valid bodies here are tiny, so holding them in memory is fine.
        body = bytearray()
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] != "http.request":  # the client went away
                return
            body.extend(message.get("body", b""))
            if len(body) > self.max_bytes:
                await _too_large()(scope, receive, send)
                return
            more_body = message.get("more_body", False)

        # 3. Hand FastAPI the body we already read, as a single message.
        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()  # afterwards, e.g. a disconnect notice

        await self.app(scope, replay_receive, send)
