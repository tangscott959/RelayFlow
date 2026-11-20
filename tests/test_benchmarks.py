"""Unit tests for the delayed sink and worker-scale benchmark helpers."""

from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer

import httpx
import pytest
from pydantic import ValidationError

from benchmarks.sink import delay_seconds, make_handler, sink_settings
from benchmarks.stats import percentile, summarize_run
from schemas.endpoint import EndpointCreate


def test_delay_seconds_clamps_negative() -> None:
    assert delay_seconds(200) == pytest.approx(0.2)
    assert delay_seconds(0) == 0.0
    assert delay_seconds(-5) == 0.0


def test_sink_settings_read_environ() -> None:
    host, port, delay_ms = sink_settings(
        {"SINK_HOST": "127.0.0.1", "SINK_PORT": "9099", "SINK_DELAY_MS": "150"}
    )
    assert host == "127.0.0.1"
    assert port == 9099
    assert delay_ms == 150


def test_percentile_nearest_rank() -> None:
    assert percentile([], 50) is None
    assert percentile([10.0], 99) == pytest.approx(10.0)
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == pytest.approx(2.0)
    with pytest.raises(ValueError, match="between 0 and 100"):
        percentile([1.0], 101)


def test_summarize_run_expected_throughput_scales_with_workers() -> None:
    one = summarize_run(
        events=30,
        workers=1,
        delay_ms=200,
        ingest_seconds=0.4,
        drain_seconds=6.0,
        delivered=30,
        duration_ms=[200.0] * 30,
    )
    three = summarize_run(
        events=30,
        workers=3,
        delay_ms=200,
        ingest_seconds=0.4,
        drain_seconds=2.0,
        delivered=30,
        duration_ms=[210.0] * 30,
    )
    assert one["expected_deliveries_per_sec"] == pytest.approx(5.0)
    assert three["expected_deliveries_per_sec"] == pytest.approx(15.0)
    assert three["deliveries_per_sec"] == pytest.approx(15.0)
    assert one["http_duration_ms_p50"] == pytest.approx(200.0)


def test_endpoint_create_accepts_compose_sink_hostname() -> None:
    parsed = EndpointCreate(
        target_url="http://sink:8089/hooks",
        subscribed_events=["*"],
        rate_limit_per_sec=1000,
    )
    assert str(parsed.target_url) == "http://sink:8089/hooks"
    with pytest.raises(ValidationError):
        EndpointCreate(target_url="not-a-url", subscribed_events=["*"])


def test_sink_post_sleeps_then_returns_200() -> None:
    slept: list[float] = []

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    handler = make_handler(50, sleeper=fake_sleep)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = int(server.server_address[1])
        health = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2.0)
        posted = httpx.post(
            f"http://127.0.0.1:{port}/hooks",
            json={"ok": True},
            timeout=2.0,
        )
        missing = httpx.get(f"http://127.0.0.1:{port}/nope", timeout=2.0)
    finally:
        server.shutdown()
        thread.join(timeout=2.0)

    assert health.status_code == 200
    assert posted.status_code == 200
    assert posted.json() == {"ok": True}
    assert missing.status_code == 404
    assert len(slept) == 1
    assert slept[0] == pytest.approx(0.05)
