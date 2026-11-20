"""Request and trace correlation for HTTP ingest and Celery delivery."""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

_TRACEPARENT_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")

request_id_ctx: ContextVar[str | None] = ContextVar("relayflow_request_id", default=None)
trace_id_ctx: ContextVar[str | None] = ContextVar("relayflow_trace_id", default=None)
tenant_id_ctx: ContextVar[str | None] = ContextVar("relayflow_tenant_id", default=None)


def new_request_id() -> str:
    return str(uuid.uuid4())


def new_trace_id() -> str:
    """Return a 32-hex trace id (W3C trace-id width)."""

    return uuid.uuid4().hex


def extract_trace_id(traceparent: str | None) -> str | None:
    """Parse the trace id from a W3C ``traceparent`` header when well-formed."""

    if not traceparent:
        return None
    parts = traceparent.strip().split("-")
    if len(parts) < 2:
        return None
    candidate = parts[1].lower()
    if _TRACEPARENT_TRACE_ID.fullmatch(candidate):
        return candidate
    return None


def bind_request_context(
    *,
    request_id: str,
    trace_id: str,
    tenant_id: str | None = None,
) -> None:
    request_id_ctx.set(request_id)
    trace_id_ctx.set(trace_id)
    if tenant_id is not None:
        tenant_id_ctx.set(tenant_id)


def bind_trace_id(trace_id: str) -> None:
    trace_id_ctx.set(trace_id)


def set_tenant_id(tenant_id: str) -> None:
    tenant_id_ctx.set(tenant_id)


def get_request_id() -> str | None:
    return request_id_ctx.get()


def get_trace_id() -> str | None:
    return trace_id_ctx.get()


def get_tenant_id() -> str | None:
    return tenant_id_ctx.get()


def clear_request_context() -> None:
    request_id_ctx.set(None)
    trace_id_ctx.set(None)
    tenant_id_ctx.set(None)
