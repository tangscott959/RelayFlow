"""In-process HTTP/ingest metrics and Redis-backed delivery counters.

HTTP and ingest run in the FastAPI process, so those series are local.
Delivery outcomes are incremented in Redis so every Celery worker replica
contributes to ``GET /metrics``.
"""

from __future__ import annotations

import logging
import re
import threading
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

INGEST_RESULTS = ("accepted", "duplicate", "rate_limited")
DELIVERY_OUTCOMES = (
    "delivered",
    "failed",
    "retrying",
    "deferred",
    "disabled",
    "skipped",
)

_UUID_SEGMENT = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

_lock = threading.Lock()
_http_requests: dict[tuple[str, str, str], int] = defaultdict(int)
_http_duration_ms_sum: dict[tuple[str, str], float] = defaultdict(float)
_http_duration_count: dict[tuple[str, str], int] = defaultdict(int)
_ingest_total: dict[str, int] = defaultdict(int)
_ingest_duration_ms_sum: float = 0.0
_ingest_duration_count: int = 0
_ingest_over_budget_total: int = 0


def normalize_path(path: str) -> str:
    """Replace UUID segments so metric labels stay low-cardinality."""

    stripped = path.split("?", 1)[0]
    return _UUID_SEGMENT.sub("{id}", stripped)


def reset_process_metrics() -> None:
    """Clear in-process series. Used by unit tests."""

    global _ingest_duration_ms_sum, _ingest_duration_count, _ingest_over_budget_total
    with _lock:
        _http_requests.clear()
        _http_duration_ms_sum.clear()
        _http_duration_count.clear()
        _ingest_total.clear()
        _ingest_duration_ms_sum = 0.0
        _ingest_duration_count = 0
        _ingest_over_budget_total = 0


def observe_http_request(
    *,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
) -> None:
    route = normalize_path(path)
    verb = method.upper()
    status = str(status_code)
    with _lock:
        _http_requests[(verb, route, status)] += 1
        _http_duration_ms_sum[(verb, route)] += duration_ms
        _http_duration_count[(verb, route)] += 1


def record_ingest(*, result: str, elapsed_ms: float, over_budget: bool) -> None:
    if result not in INGEST_RESULTS:
        result = "accepted"
    global _ingest_duration_ms_sum, _ingest_duration_count, _ingest_over_budget_total
    with _lock:
        _ingest_total[result] += 1
        _ingest_duration_ms_sum += elapsed_ms
        _ingest_duration_count += 1
        if over_budget:
            _ingest_over_budget_total += 1


def delivery_metric_key(outcome: str) -> str:
    return f"relayflow:metrics:delivery:{outcome}"


async def record_delivery(redis: Any, outcome: str) -> None:
    """Increment a delivery outcome counter. Failures here must not fail delivery."""

    if outcome not in DELIVERY_OUTCOMES:
        outcome = "failed"
    incr = getattr(redis, "incr", None)
    if incr is None:
        return
    try:
        await incr(delivery_metric_key(outcome))
    except Exception:
        logger.debug("Could not increment delivery metric %s", outcome, exc_info=True)


def render_process_metrics() -> str:
    """Prometheus text for in-process HTTP and ingest series."""

    lines: list[str] = [
        "# HELP relayflow_http_requests_total HTTP requests handled by the API.",
        "# TYPE relayflow_http_requests_total counter",
    ]
    with _lock:
        http_items = sorted(_http_requests.items())
        duration_keys = sorted(
            set(_http_duration_ms_sum.keys()) | set(_http_duration_count.keys())
        )
        ingest_items = sorted(_ingest_total.items())
        duration_sum = _ingest_duration_ms_sum
        duration_count = _ingest_duration_count
        over_budget = _ingest_over_budget_total

    for (method, path, status), count in http_items:
        lines.append(
            "relayflow_http_requests_total"
            f'{{method="{_escape(method)}",path="{_escape(path)}",status="{_escape(status)}"}} {count}'
        )

    lines.append("# HELP relayflow_http_request_duration_milliseconds_sum HTTP handler time.")
    lines.append("# TYPE relayflow_http_request_duration_milliseconds_sum counter")
    lines.append("# HELP relayflow_http_request_duration_milliseconds_count HTTP handler samples.")
    lines.append("# TYPE relayflow_http_request_duration_milliseconds_count counter")
    for method, path in duration_keys:
        summed = _http_duration_ms_sum.get((method, path), 0.0)
        count = _http_duration_count.get((method, path), 0)
        labels = f'method="{_escape(method)}",path="{_escape(path)}"'
        lines.append(f"relayflow_http_request_duration_milliseconds_sum{{{labels}}} {summed:.3f}")
        lines.append(f"relayflow_http_request_duration_milliseconds_count{{{labels}}} {count}")

    lines.append("# HELP relayflow_ingest_total Event ingest outcomes.")
    lines.append("# TYPE relayflow_ingest_total counter")
    known = {result: 0 for result in INGEST_RESULTS}
    known.update(ingest_items)
    for result, count in known.items():
        lines.append(f'relayflow_ingest_total{{result="{_escape(result)}"}} {count}')

    lines.append("# HELP relayflow_ingest_duration_milliseconds_sum Ingest path time.")
    lines.append("# TYPE relayflow_ingest_duration_milliseconds_sum counter")
    lines.append(f"relayflow_ingest_duration_milliseconds_sum {duration_sum:.3f}")
    lines.append("# HELP relayflow_ingest_duration_milliseconds_count Ingest path samples.")
    lines.append("# TYPE relayflow_ingest_duration_milliseconds_count counter")
    lines.append(f"relayflow_ingest_duration_milliseconds_count {duration_count}")
    lines.append(
        "# HELP relayflow_ingest_over_budget_total Ingest calls slower than the 15ms budget."
    )
    lines.append("# TYPE relayflow_ingest_over_budget_total counter")
    lines.append(f"relayflow_ingest_over_budget_total {over_budget}")
    return "\n".join(lines) + "\n"


async def render_delivery_metrics(redis: Any) -> str:
    """Prometheus text for Redis-backed delivery counters."""

    lines = [
        "# HELP relayflow_delivery_total Outbound delivery outcomes across workers.",
        "# TYPE relayflow_delivery_total counter",
    ]
    getter = getattr(redis, "get", None)
    if getter is None:
        for outcome in DELIVERY_OUTCOMES:
            lines.append(f'relayflow_delivery_total{{outcome="{outcome}"}} 0')
        return "\n".join(lines) + "\n"

    for outcome in DELIVERY_OUTCOMES:
        raw: str | None = None
        try:
            raw = await getter(delivery_metric_key(outcome))
        except Exception:
            logger.debug("Could not read delivery metric %s", outcome, exc_info=True)
        count = int(raw) if raw else 0
        lines.append(f'relayflow_delivery_total{{outcome="{outcome}"}} {count}')
    return "\n".join(lines) + "\n"


async def increment_delivery_outcome(outcome: str, redis: Any | None = None) -> None:
    """Increment a delivery counter, opening a short-lived Redis client if needed."""

    owned = False
    client = redis
    if client is None:
        from redis.asyncio import Redis

        from core.config import settings

        client = Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        owned = True
    try:
        await record_delivery(client, outcome)
    finally:
        if owned:
            aclose = getattr(client, "aclose", None)
            if aclose is not None:
                await aclose()


def render_prometheus(process_text: str, delivery_text: str) -> str:
    return process_text.rstrip("\n") + "\n" + delivery_text.lstrip("\n")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
