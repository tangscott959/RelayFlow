"""Idempotency, subscriber matching, and dead-letter resend tests."""

from __future__ import annotations

import uuid

import pytest

from models import DeliveryAttempt, DeliveryStatus, EndpointStatus, WebhookEndpoint, WebhookEvent
from services.dispatcher import (
    _idempotency_redis_key,
    dispatch_event,
    resend_dead_letter,
)
from tests.fakes import InMemoryRedis


def test_idempotency_redis_key_format() -> None:
    tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    assert (
        _idempotency_redis_key(tenant_id, "evt-1")
        == "relayflow:idempotency:00000000-0000-0000-0000-000000000001:evt-1"
    )


async def test_dispatch_short_circuits_on_redis_hit(memory_redis: InMemoryRedis) -> None:
    tenant_id = uuid.uuid4()
    event_id = uuid.uuid4()
    memory_redis.values[_idempotency_redis_key(tenant_id, "dup-1")] = str(event_id)

    result = await dispatch_event(
        session=object(),  # type: ignore[arg-type]
        redis=memory_redis,  # type: ignore[arg-type]
        tenant_id=tenant_id,
        event_type="agent.completed",
        idempotency_key="dup-1",
        payload={"ok": True},
    )

    assert result.duplicate is True
    assert result.event_id == event_id
    assert result.attempt_ids == []


@pytest.mark.integration
async def test_dispatch_unique_constraint_is_treated_as_duplicate(
    require_backend: None,
    tenant_id: uuid.UUID,
    memory_redis: InMemoryRedis,
) -> None:
    from db.session import AsyncSessionLocal

    idempotency_key = f"evt-{uuid.uuid4()}"
    async with AsyncSessionLocal() as session:
        existing = WebhookEvent(
            tenant_id=tenant_id,
            event_type="agent.completed",
            idempotency_key=idempotency_key,
            payload={"seed": True},
        )
        session.add(existing)
        await session.commit()
        await session.refresh(existing)

    async with AsyncSessionLocal() as session:
        result = await dispatch_event(
            session=session,
            redis=memory_redis,  # type: ignore[arg-type]
            tenant_id=tenant_id,
            event_type="agent.completed",
            idempotency_key=idempotency_key,
            payload={"seed": False},
        )

    assert result.duplicate is True
    assert result.event_id == existing.id
    assert result.attempt_ids == []
    assert memory_redis.values[_idempotency_redis_key(tenant_id, idempotency_key)] == str(existing.id)


@pytest.mark.integration
async def test_dispatch_fans_out_to_matching_active_endpoints(
    require_backend: None,
    tenant_id: uuid.UUID,
    memory_redis: InMemoryRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from db.session import AsyncSessionLocal

    monkeypatch.setattr("services.dispatcher._schedule_deliveries", lambda attempt_ids: None)

    async with AsyncSessionLocal() as session:
        wildcard = WebhookEndpoint(
            tenant_id=tenant_id,
            target_url="https://example.com/all",
            secret_key="whsec_all",
            subscribed_events=["*"],
            status=EndpointStatus.ACTIVE,
        )
        typed = WebhookEndpoint(
            tenant_id=tenant_id,
            target_url="https://example.com/typed",
            secret_key="whsec_typed",
            subscribed_events=["agent.completed"],
            status=EndpointStatus.ACTIVE,
        )
        paused = WebhookEndpoint(
            tenant_id=tenant_id,
            target_url="https://example.com/paused",
            secret_key="whsec_paused",
            subscribed_events=["*"],
            status=EndpointStatus.PAUSED,
        )
        other_type = WebhookEndpoint(
            tenant_id=tenant_id,
            target_url="https://example.com/other",
            secret_key="whsec_other",
            subscribed_events=["order.created"],
            status=EndpointStatus.ACTIVE,
        )
        session.add_all([wildcard, typed, paused, other_type])
        await session.commit()

        result = await dispatch_event(
            session=session,
            redis=memory_redis,  # type: ignore[arg-type]
            tenant_id=tenant_id,
            event_type="agent.completed",
            idempotency_key=f"evt-{uuid.uuid4()}",
            payload={"ok": True},
        )

    assert result.duplicate is False
    assert len(result.attempt_ids) == 2


@pytest.mark.integration
async def test_resend_dead_letter_queues_next_attempt(
    require_backend: None,
    tenant_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from db.session import AsyncSessionLocal

    scheduled: list[uuid.UUID] = []
    monkeypatch.setattr(
        "services.dispatcher._schedule_deliveries",
        lambda attempt_ids: scheduled.extend(attempt_ids),
    )

    async with AsyncSessionLocal() as session:
        endpoint = WebhookEndpoint(
            tenant_id=tenant_id,
            target_url="https://example.com/hook",
            secret_key="whsec_dlq",
            subscribed_events=["*"],
        )
        event = WebhookEvent(
            tenant_id=tenant_id,
            event_type="agent.completed",
            idempotency_key=f"evt-{uuid.uuid4()}",
            payload={"ok": False},
        )
        session.add_all([endpoint, event])
        await session.flush()
        failed = DeliveryAttempt(
            event_id=event.id,
            endpoint_id=endpoint.id,
            attempt_number=5,
            status=DeliveryStatus.FAILED,
        )
        session.add(failed)
        await session.commit()
        await session.refresh(failed)

        replay = await resend_dead_letter(
            session=session,
            tenant_id=tenant_id,
            attempt_id=failed.id,
        )

        with pytest.raises(ValueError, match="FAILED"):
            await resend_dead_letter(
                session=session,
                tenant_id=tenant_id,
                attempt_id=replay.id,
            )

        with pytest.raises(LookupError, match="not found"):
            await resend_dead_letter(
                session=session,
                tenant_id=uuid.uuid4(),
                attempt_id=failed.id,
            )

    assert replay.status == DeliveryStatus.PENDING
    assert replay.attempt_number == 6
    assert scheduled == [replay.id]
