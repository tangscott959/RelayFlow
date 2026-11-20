"""JSON structured logging with request and trace correlation fields."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from core.tracing import get_request_id, get_tenant_id, get_trace_id

_RESERVED_RECORD_KEYS = frozenset(
    {
        "name",
        "msg",
        "args",
        "created",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "exc_info",
        "exc_text",
        "thread",
        "threadName",
        "message",
        "taskName",
        "request_id",
        "trace_id",
        "tenant_id",
        "asctime",
    }
)


class ContextFilter(logging.Filter):
    """Copy correlation ids from context vars onto every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        record.trace_id = get_trace_id() or "-"
        record.tenant_id = get_tenant_id() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line for aggregators and Compose logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id and request_id != "-":
            payload["request_id"] = request_id
        trace_id = getattr(record, "trace_id", None)
        if trace_id and trace_id != "-":
            payload["trace_id"] = trace_id
        tenant_id = getattr(record, "tenant_id", None)
        if tenant_id and tenant_id != "-":
            payload["tenant_id"] = tenant_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_KEYS or value is None:
                continue
            payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging(*, force: bool = False) -> None:
    """Attach a JSON stream handler to the root logger once."""

    from core.config import settings

    root = logging.getLogger()
    existing = [
        handler
        for handler in root.handlers
        if getattr(handler, "_relayflow_json", False)
    ]
    if existing and not force:
        return

    level = logging.DEBUG if settings.debug else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ContextFilter())
    handler._relayflow_json = True  # type: ignore[attr-defined]
    if force:
        for old in existing:
            root.removeHandler(old)
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
