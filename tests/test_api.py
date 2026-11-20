"""HTTP contract tests and in-process API integration tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from models import DeliveryAttempt, DeliveryStatus, WebhookEvent
from schemas.event import EventIngestRequest


async def test_health_ok(contract_client: AsyncClient) -> None:
    response = await contract_client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "RelayFlow"


async def test_business_routes_require_bearer_token(contract_client: AsyncClient) -> None:
    response = await contract_client.get("/api/v1/endpoints")
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


async def test_malformed_api_key_is_rejected(contract_client: AsyncClient) -> None:
    response = await contract_client.get(
        "/api/v1/endpoints",
        headers={"Authorization": "Bearer not-an-api-key"},
    )
    assert response.status_code == 401


async def test_unknown_api_key_is_rejected(contract_client: AsyncClient) -> None:
    response = await contract_client.get(
        "/api/v1/endpoints",
        headers={"Authorization": "Bearer rfk_unknown_token_value"},
    )
    assert response.status_code == 401


async def test_ingest_rejects_blank_event_type(authed_contract_client: AsyncClient) -> None:
    response = await authed_contract_client.post(
        "/api/v1/events",
        json={"event_type": "   ", "idempotency_key": "k1", "payload": {}},
    )
    assert response.status_code == 422


async def test_create_endpoint_rejects_invalid_url(authed_contract_client: AsyncClient) -> None:
    response = await authed_contract_client.post(
        "/api/v1/endpoints",
        json={"target_url": "not-a-url", "subscribed_events": ["*"]},
    )
    assert response.status_code == 422


async def test_register_tenant_rejects_blank_name(contract_client: AsyncClient) -> None:
    response = await contract_client.post("/api/v1/tenants", json={"name": "   "})
    assert response.status_code == 422


def test_event_ingest_schema_strips_and_rejects_blank() -> None:
    parsed = EventIngestRequest(
        event_type="  agent.completed  ",
        idempotency_key="  evt-1  ",
        payload={"ok": True},
    )
    assert parsed.event_type == "agent.completed"
    assert parsed.idempotency_key == "evt-1"

    with pytest.raises(ValidationError):
        EventIngestRequest(event_type=" ", idempotency_key="k", payload={})


@pytest.mark.integration
async def test_register_tenant_and_read_me(
    api_client: AsyncClient,
    registered_tenant: dict[str, str],
    tenant_headers: dict[str, str],
) -> None:
    me = await api_client.get("/api/v1/tenants/me", headers=tenant_headers)
    assert me.status_code == 200
    body = me.json()
    assert body["id"] == registered_tenant["id"]
    assert body["api_key_prefix"] == registered_tenant["api_key_prefix"]
    assert "api_key" not in body


@pytest.mark.integration
async def test_endpoint_create_list_and_tenant_isolation(
    api_client: AsyncClient,
    tenant_headers: dict[str, str],
) -> None:
    created = await api_client.post(
        "/api/v1/endpoints",
        headers=tenant_headers,
        json={
            "target_url": "https://example.com/hooks",
            "subscribed_events": ["*", "agent.completed"],
            "rate_limit_per_sec": 5,
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["secret_key"].startswith("whsec_")
    assert body["subscribed_events"] == ["*", "agent.completed"]
    assert body["status"] == "active"

    listed = await api_client.get("/api/v1/endpoints", headers=tenant_headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    other = await api_client.post("/api/v1/tenants", json={"name": "other-tenant"})
    assert other.status_code == 201
    other_listed = await api_client.get(
        "/api/v1/endpoints",
        headers={"Authorization": f"Bearer {other.json()['api_key']}"},
    )
    assert other_listed.status_code == 200
    assert other_listed.json() == []


@pytest.mark.integration
async def test_ingest_is_idempotent_and_returns_202(
    api_client: AsyncClient,
    tenant_headers: dict[str, str],
) -> None:
    endpoint = await api_client.post(
        "/api/v1/endpoints",
        headers=tenant_headers,
        json={"target_url": "https://example.com/hooks", "subscribed_events": ["*"]},
    )
    assert endpoint.status_code == 201
    idempotency_key = f"evt-{uuid.uuid4()}"
    payload = {
        "event_type": "agent.completed",
        "idempotency_key": idempotency_key,
        "payload": {"ok": True},
    }

    first = await api_client.post("/api/v1/events", headers=tenant_headers, json=payload)
    assert first.status_code == 202
    first_body = first.json()
    assert first_body["status"] == "accepted"
    assert first_body["attempt_count"] == 1

    second = await api_client.post("/api/v1/events", headers=tenant_headers, json=payload)
    assert second.status_code == 202
    second_body = second.json()
    assert second_body["status"] == "duplicate"
    assert second_body["event_id"] == first_body["event_id"]
    assert second_body["attempt_count"] == 0


async def test_ingest_returns_429_when_rate_limited(
    authed_contract_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.rate_limit import RateLimitExceeded

    async def _limited(**kwargs: object) -> None:
        raise RateLimitExceeded(retry_after=2, scope="ingest")

    monkeypatch.setattr("api.v1.events.dispatch_event", _limited)
    response = await authed_contract_client.post(
        "/api/v1/events",
        json={"event_type": "agent.completed", "idempotency_key": "k-limit", "payload": {}},
    )
    assert response.status_code == 429
    assert response.headers.get("retry-after") == "2"
    assert response.json()["detail"] == "Ingest rate limit exceeded."


@pytest.mark.integration
async def test_ingest_rate_limit_skips_duplicates(
    api_client: AsyncClient,
    tenant_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "ingest_rate_limit_per_sec", 1)
    created = await api_client.post(
        "/api/v1/endpoints",
        headers=tenant_headers,
        json={"target_url": "https://example.com/hooks", "subscribed_events": ["*"]},
    )
    assert created.status_code == 201
    first_payload = {
        "event_type": "agent.completed",
        "idempotency_key": f"limit-{uuid.uuid4()}",
        "payload": {"n": 1},
    }
    first = await api_client.post("/api/v1/events", headers=tenant_headers, json=first_payload)
    assert first.status_code == 202
    duplicate = await api_client.post("/api/v1/events", headers=tenant_headers, json=first_payload)
    assert duplicate.status_code == 202
    assert duplicate.json()["status"] == "duplicate"
    second = await api_client.post(
        "/api/v1/events",
        headers=tenant_headers,
        json={
            "event_type": "agent.completed",
            "idempotency_key": f"limit-{uuid.uuid4()}",
            "payload": {"n": 2},
        },
    )
    assert second.status_code == 429
    assert second.headers.get("retry-after") is not None


@pytest.mark.integration
async def test_delivery_log_pagination_and_dlq_resend(
    api_client: AsyncClient,
    tenant_headers: dict[str, str],
    registered_tenant_id: uuid.UUID,
) -> None:
    from db.session import AsyncSessionLocal

    created = await api_client.post(
        "/api/v1/endpoints",
        headers=tenant_headers,
        json={"target_url": "https://example.com/hooks", "subscribed_events": ["*"]},
    )
    endpoint_id = uuid.UUID(created.json()["id"])

    for index in range(2):
        ingest = await api_client.post(
            "/api/v1/events",
            headers=tenant_headers,
            json={
                "event_type": "agent.completed",
                "idempotency_key": f"page-{uuid.uuid4()}",
                "payload": {"n": index},
            },
        )
        assert ingest.status_code == 202

    page = await api_client.get(
        f"/api/v1/endpoints/{endpoint_id}/deliveries",
        headers=tenant_headers,
        params={"page": 1, "page_size": 1},
    )
    assert page.status_code == 200
    page_body = page.json()
    assert page_body["total"] == 2
    assert page_body["page"] == 1
    assert page_body["page_size"] == 1
    assert len(page_body["items"]) == 1

    missing = await api_client.get(
        f"/api/v1/endpoints/{uuid.uuid4()}/deliveries",
        headers=tenant_headers,
    )
    assert missing.status_code == 404

    pending_id = uuid.UUID(page_body["items"][0]["id"])
    conflict = await api_client.post(
        f"/api/v1/deliveries/{pending_id}/resend",
        headers=tenant_headers,
    )
    assert conflict.status_code == 409

    async with AsyncSessionLocal() as session:
        event = WebhookEvent(
            tenant_id=registered_tenant_id,
            event_type="agent.completed",
            idempotency_key=f"dlq-{uuid.uuid4()}",
            payload={"dead": True},
        )
        session.add(event)
        await session.flush()
        failed = DeliveryAttempt(
            event_id=event.id,
            endpoint_id=endpoint_id,
            attempt_number=5,
            status=DeliveryStatus.FAILED,
        )
        session.add(failed)
        await session.commit()
        await session.refresh(failed)
        failed_id = failed.id

    resent = await api_client.post(
        f"/api/v1/deliveries/{failed_id}/resend",
        headers=tenant_headers,
    )
    assert resent.status_code == 202
    resent_body = resent.json()
    assert resent_body["status"] == "pending"
    assert resent_body["attempt_number"] == 6

    unknown = await api_client.post(
        f"/api/v1/deliveries/{uuid.uuid4()}/resend",
        headers=tenant_headers,
    )
    assert unknown.status_code == 404
