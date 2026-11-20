"""Ingest events and measure drain time against the delayed Compose sink.

The API is called from the host (``http://localhost:8000``). Workers POST to
the Docker DNS name ``http://sink:8089/hooks`` so injected latency applies
inside the Compose network.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from typing import Any

import httpx

from benchmarks.stats import summarize_run

DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_TARGET_URL = "http://sink:8089/hooks"


async def _register(
    client: httpx.AsyncClient,
    *,
    target_url: str,
    rate_limit_per_sec: int,
) -> tuple[str, str]:
    tenant = await client.post(
        "/api/v1/tenants",
        json={"name": f"bench-{uuid.uuid4().hex[:8]}"},
    )
    tenant.raise_for_status()
    api_key = tenant.json()["api_key"]
    headers = {"Authorization": f"Bearer {api_key}"}
    endpoint = await client.post(
        "/api/v1/endpoints",
        headers=headers,
        json={
            "target_url": target_url,
            "subscribed_events": ["*"],
            "rate_limit_per_sec": rate_limit_per_sec,
        },
    )
    endpoint.raise_for_status()
    return api_key, str(endpoint.json()["id"])


async def _ingest_batch(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    events: int,
    concurrency: int,
) -> float:
    headers = {"Authorization": f"Bearer {api_key}"}
    semaphore = asyncio.Semaphore(max(concurrency, 1))
    started = time.perf_counter()

    async def _one(index: int) -> None:
        async with semaphore:
            response = await client.post(
                "/api/v1/events",
                headers=headers,
                json={
                    "event_type": "agent.completed",
                    "idempotency_key": f"bench-{index}-{uuid.uuid4()}",
                    "payload": {"n": index},
                },
            )
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", "1"))
                await asyncio.sleep(retry_after)
                response = await client.post(
                    "/api/v1/events",
                    headers=headers,
                    json={
                        "event_type": "agent.completed",
                        "idempotency_key": f"bench-{index}-{uuid.uuid4()}",
                        "payload": {"n": index},
                    },
                )
            response.raise_for_status()
            body = response.json()
            if body.get("attempt_count", 0) < 1:
                raise RuntimeError("Ingest returned zero attempts; is the endpoint active?")

    await asyncio.gather(*[_one(i) for i in range(events)])
    return time.perf_counter() - started


async def _wait_for_delivered(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    endpoint_id: str,
    expected: int,
    timeout_s: float,
) -> tuple[int, list[float]]:
    headers = {"Authorization": f"Bearer {api_key}"}
    deadline = time.perf_counter() + timeout_s
    delivered = 0
    durations: list[float] = []
    while time.perf_counter() < deadline:
        response = await client.get(
            f"/api/v1/endpoints/{endpoint_id}/deliveries",
            headers=headers,
            params={"status": "delivered", "page": 1, "page_size": min(expected, 100)},
        )
        response.raise_for_status()
        payload = response.json()
        delivered = int(payload["total"])
        durations = [
            float(item["duration_ms"])
            for item in payload["items"]
            if item.get("duration_ms") is not None
        ]
        if delivered >= expected:
            return delivered, durations
        await asyncio.sleep(0.25)
    return delivered, durations


async def _ensure_sink(health_url: str) -> None:
    if not health_url:
        return
    async with httpx.AsyncClient(timeout=5.0) as probe:
        response = await probe.get(health_url)
        response.raise_for_status()


async def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    await _ensure_sink(args.sink_health_url)
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(base_url=args.api_url.rstrip("/"), timeout=timeout) as client:
        health = await client.get("/health")
        health.raise_for_status()
        api_key, endpoint_id = await _register(
            client,
            target_url=args.target_url,
            rate_limit_per_sec=args.rate_limit_per_sec,
        )
        drain_started = time.perf_counter()
        ingest_seconds = await _ingest_batch(
            client,
            api_key=api_key,
            events=args.events,
            concurrency=args.ingest_concurrency,
        )
        delivered, durations = await _wait_for_delivered(
            client,
            api_key=api_key,
            endpoint_id=endpoint_id,
            expected=args.events,
            timeout_s=args.timeout,
        )
        drain_seconds = time.perf_counter() - drain_started
    report = summarize_run(
        events=args.events,
        workers=args.workers,
        delay_ms=args.delay_ms,
        ingest_seconds=ingest_seconds,
        drain_seconds=drain_seconds,
        delivered=delivered,
        duration_ms=durations,
    )
    report["endpoint_id"] = endpoint_id
    report["complete"] = delivered >= args.events
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RelayFlow worker-scale benchmark.")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument(
        "--target-url",
        default=DEFAULT_TARGET_URL,
        help="URL workers POST to (Compose DNS: http://sink:8089/hooks).",
    )
    parser.add_argument("--events", type=int, default=30)
    parser.add_argument("--workers", type=int, default=1, help="Compose worker replica count.")
    parser.add_argument("--delay-ms", type=int, default=200, help="Sink sleep; must match SINK_DELAY_MS.")
    parser.add_argument("--ingest-concurrency", type=int, default=10)
    parser.add_argument("--rate-limit-per-sec", type=int, default=1000)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--sink-health-url",
        default="http://localhost:8089/health",
        help="Host-side sink probe. Empty string skips the check.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = asyncio.run(run_benchmark(args))
    except httpx.HTTPError as exc:
        print(f"benchmark HTTP error: {exc}", file=sys.stderr)
        return 1
    except (RuntimeError, OSError) as exc:
        print(f"benchmark failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    if not report["complete"]:
        print(
            f"timed out: delivered {report['delivered']}/{report['events']}",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
