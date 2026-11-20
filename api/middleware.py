"""HTTP middleware for correlation ids, structured access logs, and metrics."""

from __future__ import annotations

import logging
import time
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.metrics import observe_http_request
from core.tracing import (
    bind_request_context,
    clear_request_context,
    extract_trace_id,
    new_request_id,
    new_trace_id,
)

logger = logging.getLogger(__name__)

_QUIET_PATHS = frozenset({"/health", "/metrics"})


class ObservabilityMiddleware:
    """Bind request/trace ids, record HTTP metrics, and echo correlation headers.

    Implemented as raw ASGI so context vars propagate into FastAPI handlers
    (Starlette ``BaseHTTPMiddleware`` can run the inner app on a different task).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        header_map = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        request_id = header_map.get("x-request-id") or new_request_id()
        trace_id = extract_trace_id(header_map.get("traceparent")) or new_trace_id()
        bind_request_context(request_id=request_id, trace_id=trace_id)

        started = time.perf_counter()
        method = str(scope.get("method", "GET"))
        path = str(scope.get("path", "/"))
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = list(message.get("headers") or [])
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                headers.append((b"x-trace-id", trace_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            observe_http_request(
                method=method,
                path=path,
                status_code=500,
                duration_ms=duration_ms,
            )
            clear_request_context()
            raise

        duration_ms = (time.perf_counter() - started) * 1000
        observe_http_request(
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
        )
        if path not in _QUIET_PATHS:
            logger.info(
                "http_request",
                extra={
                    "event": "http.request",
                    "method": method,
                    "path": path,
                    "status": status_code,
                    "duration_ms": round(duration_ms, 3),
                },
            )
        clear_request_context()
