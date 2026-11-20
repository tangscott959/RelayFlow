"""Structured logs, correlation ids, and Prometheus metrics."""

from __future__ import annotations

import json
import logging
import uuid

import pytest
from httpx import AsyncClient

from core.logging import ContextFilter, JsonFormatter
from core.metrics import (
    delivery_metric_key,
    normalize_path,
    record_delivery,
    record_ingest,
    render_delivery_metrics,
    render_process_metrics,
    reset_process_metrics,
)
from core.tracing import (
    bind_request_context,
    clear_request_context,
    extract_trace_id,
    new_trace_id,
)
from services.dispatcher import _enqueue_delivery, _idempotency_redis_key, dispatch_event
from tests.fakes import InMemoryRedis


def test_json_formatter_includes_correlation_fields() -> None:
    bind_request_context(request_id="req-1", trace_id="a" * 32, tenant_id="tenant-9")
    record = logging.LogRecord(
        name="relayflow.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    ContextFilter().filter(record)
    payload = json.loads(JsonFormatter().format(record))
    clear_request_context()

    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["request_id"] == "req-1"
    assert payload["trace_id"] == "a" * 32
    assert payload["tenant_id"] == "tenant-9"


def test_extract_trace_id_from_traceparent() -> None:
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    assert extract_trace_id(f"00-{trace_id}-00f067aa0ba902b7-01") == trace_id
    assert extract_trace_id("not-a-header") is None
    assert extract_trace_id(None) is None
    assert len(new_trace_id()) == 32


def test_normalize_path_replaces_uuid_segments() -> None:
    endpoint_id = uuid.uuid4()
    assert (
        normalize_path(f"/api/v1/endpoints/{endpoint_id}/deliveries?status=failed")
        == "/api/v1/endpoints/{id}/deliveries"
    )


def test_ingest_over_budget_is_counted() -> None:
    reset_process_metrics()
    record_ingest(result="accepted", elapsed_ms=21.5, over_budget=True)
    text = render_process_metrics()
    assert 'relayflow_ingest_total{result="accepted"} 1' in text
    assert "relayflow_ingest_over_budget_total 1" in text
    assert "relayflow_ingest_duration_milliseconds_sum 21.500" in text


async def test_delivery_counters_render_from_redis() -> None:
    redis = InMemoryRedis()
    await record_delivery(redis, "delivered")
    await record_delivery(redis, "delivered")
    await record_delivery(redis, "failed")
    text = await render_delivery_metrics(redis)
    assert redis.values[delivery_metric_key("delivered")] == "2"
    assert 'relayflow_delivery_total{outcome="delivered"} 2' in text
    assert 'relayflow_delivery_total{outcome="failed"} 1' in text
    assert 'relayflow_delivery_total{outcome="deferred"} 0' in text


def test_enqueue_delivery_passes_trace_id(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict[str, object] = {}

    def fake_send_task(
        name: str,
        args: list[str] | None = None,
        kwargs: dict[str, str] | None = None,
    ) -> None:
        sent["name"] = name
        sent["args"] = args
        sent["kwargs"] = kwargs

    monkeypatch.setattr("services.dispatcher.celery_app.send_task", fake_send_task)
    _enqueue_delivery("attempt-1", "c" * 32)
    assert sent["name"] == "workers.delivery.deliver_webhook_task"
    assert sent["args"] == ["attempt-1"]
    assert sent["kwargs"] == {"trace_id": "c" * 32}


async def test_dispatch_duplicate_increments_ingest_metric(
    memory_redis: InMemoryRedis,
) -> None:
    reset_process_metrics()
    tenant_id = uuid.uuid4()
    event_id = uuid.uuid4()
    memory_redis.values[_idempotency_redis_key(tenant_id, "dup-obs")] = str(event_id)

    result = await dispatch_event(
        session=object(),  # type: ignore[arg-type]
        redis=memory_redis,  # type: ignore[arg-type]
        tenant_id=tenant_id,
        event_type="agent.completed",
        idempotency_key="dup-obs",
        payload={"ok": True},
    )

    assert result.duplicate is True
    assert 'relayflow_ingest_total{result="duplicate"} 1' in render_process_metrics()


async def test_health_echoes_request_and_trace_ids(contract_client: AsyncClient) -> None:
    reset_process_metrics()
    trace_id = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    response = await contract_client.get(
        "/health",
        headers={
            "X-Request-ID": "client-req-1",
            "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
        },
    )
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "client-req-1"
    assert response.headers["x-trace-id"] == trace_id


async def test_metrics_endpoint_exposes_http_and_ingest_series(
    contract_client: AsyncClient,
) -> None:
    reset_process_metrics()
    await contract_client.get("/health")
    response = await contract_client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "relayflow_http_requests_total" in body
    assert 'path="/health"' in body
    assert "relayflow_ingest_total" in body
    assert "relayflow_delivery_total" in body


async def test_metrics_normalize_endpoint_id_path(
    authed_contract_client: AsyncClient,
) -> None:
    reset_process_metrics()
    endpoint_id = uuid.uuid4()
    await authed_contract_client.get(f"/api/v1/endpoints/{endpoint_id}")
    response = await authed_contract_client.get("/metrics")
    assert 'path="/api/v1/endpoints/{id}"' in response.text
    assert str(endpoint_id) not in response.text
