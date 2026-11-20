"""Summary statistics for worker-scale benchmark runs."""

from __future__ import annotations

import math
from typing import Any


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile. ``p`` is in 0..100. Empty input returns None."""

    if not 0.0 <= p <= 100.0:
        raise ValueError("percentile p must be between 0 and 100.")
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil((p / 100.0) * len(ordered)))
    return float(ordered[rank - 1])


def summarize_run(
    *,
    events: int,
    workers: int,
    delay_ms: int,
    ingest_seconds: float,
    drain_seconds: float,
    delivered: int,
    duration_ms: list[float],
) -> dict[str, Any]:
    """Build a JSON-serializable report for one (workers, delay) configuration."""

    throughput = (delivered / drain_seconds) if drain_seconds > 0 else 0.0
    expected = (workers * 1000.0 / delay_ms) if delay_ms > 0 else None
    p50 = percentile(duration_ms, 50.0)
    p99 = percentile(duration_ms, 99.0)
    return {
        "events": events,
        "workers": workers,
        "sink_delay_ms": delay_ms,
        "delivered": delivered,
        "ingest_seconds": round(ingest_seconds, 3),
        "drain_seconds": round(drain_seconds, 3),
        "deliveries_per_sec": round(throughput, 3),
        "expected_deliveries_per_sec": None if expected is None else round(expected, 3),
        "http_duration_ms_p50": None if p50 is None else round(p50, 1),
        "http_duration_ms_p99": None if p99 is None else round(p99, 1),
    }
