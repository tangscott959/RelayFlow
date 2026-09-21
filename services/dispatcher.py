"""Fan-out dispatcher: persist an event and enqueue delivery tasks quickly."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import DeliveryAttempt, DeliveryStatus, EndpointStatus, WebhookEndpoint, WebhookEvent
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)

IDEMPOTENCY_TTL_SECONDS: int = 86_400
DISPATCH_BUDGET_MS: float = 15.0


@dataclass(slots=True)
class DispatchResult:
    event_id: uuid.UUID
    duplicate: bool
    attempt_ids: list[uuid.UUID] = field(default_factory=list)


def _idempotency_redis_key(tenant_id: uuid.UUID, idempotency_key: str) -> str:
    return f"relayflow:idempotency:{tenant_id}:{idempotency_key}"


def _enqueue_delivery(attempt_id: str) -> None:
    """Publish a delivery task by name to avoid a workers <-> services import cycle."""
    celery_app.send_task("workers.delivery.deliver_webhook_task", args=[attempt_id])


def _schedule_deliveries(attempt_ids: list[uuid.UUID]) -> None:
    """Enqueue Celery tasks without awaiting broker round-trips on the event loop.

    ``delay()`` is synchronous Redis I/O. Scheduling it on the default executor
    keeps the ingest path inside the 15ms budget while still publishing tasks
    after the database transaction has committed.
    """
    loop = asyncio.get_running_loop()
    for attempt_id in attempt_ids:
        loop.run_in_executor(None, _enqueue_delivery, str(attempt_id))


def _matching_endpoints_stmt(tenant_id: uuid.UUID, event_type: str) -> Select[tuple[WebhookEndpoint]]:
    return select(WebhookEndpoint).where(
        WebhookEndpoint.tenant_id == tenant_id,
        WebhookEndpoint.status == EndpointStatus.ACTIVE,
        or_(
            WebhookEndpoint.subscribed_events.contains([event_type]),
            WebhookEndpoint.subscribed_events.contains(["*"]),
        ),
    )


async def _load_event_by_idempotency(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    idempotency_key: str,
) -> WebhookEvent | None:
    stmt = select(WebhookEvent).where(
        WebhookEvent.tenant_id == tenant_id,
        WebhookEvent.idempotency_key == idempotency_key,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def dispatch_event(
    *,
    session: AsyncSession,
    redis: Redis,
    tenant_id: uuid.UUID,
    event_type: str,
    idempotency_key: str,
    payload: dict[str, Any],
) -> DispatchResult:
    """Persist an event, create PENDING attempts, and enqueue Celery deliveries.

    The hot path is Redis GET + one DB transaction + non-blocking Celery
    publishes. Duplicate ``idempotency_key`` values short-circuit before fan-out.
    """
    started = time.perf_counter()
    redis_key = _idempotency_redis_key(tenant_id, idempotency_key)

    cached_event_id = await redis.get(redis_key)
    if cached_event_id:
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info("Idempotent hit for %s in %.2fms", idempotency_key, elapsed_ms)
        return DispatchResult(
            event_id=uuid.UUID(str(cached_event_id)),
            duplicate=True,
            attempt_ids=[],
        )

    event = WebhookEvent(
        tenant_id=tenant_id,
        event_type=event_type,
        idempotency_key=idempotency_key,
        payload=payload,
    )
    session.add(event)

    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = await _load_event_by_idempotency(session, tenant_id, idempotency_key)
        if existing is None:
            raise
        await redis.set(redis_key, str(existing.id), ex=IDEMPOTENCY_TTL_SECONDS)
        return DispatchResult(event_id=existing.id, duplicate=True, attempt_ids=[])

    endpoint_result = await session.execute(_matching_endpoints_stmt(tenant_id, event_type))
    endpoints = list(endpoint_result.scalars().all())

    attempts: list[DeliveryAttempt] = [
        DeliveryAttempt(
            event_id=event.id,
            endpoint_id=endpoint.id,
            attempt_number=1,
            status=DeliveryStatus.PENDING,
        )
        for endpoint in endpoints
    ]
    session.add_all(attempts)
    await session.flush()
    attempt_ids = [attempt.id for attempt in attempts]
    await session.commit()

    await redis.set(redis_key, str(event.id), ex=IDEMPOTENCY_TTL_SECONDS)
    if attempt_ids:
        _schedule_deliveries(attempt_ids)

    elapsed_ms = (time.perf_counter() - started) * 1000
    if elapsed_ms > DISPATCH_BUDGET_MS:
        logger.warning(
            "Dispatch exceeded %.1fms budget (%.2fms) event=%s attempts=%s",
            DISPATCH_BUDGET_MS,
            elapsed_ms,
            event.id,
            len(attempt_ids),
        )
    else:
        logger.info(
            "Dispatched event %s to %s endpoint(s) in %.2fms",
            event.id,
            len(attempt_ids),
            elapsed_ms,
        )

    return DispatchResult(event_id=event.id, duplicate=False, attempt_ids=attempt_ids)


async def resend_dead_letter(
    *,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    attempt_id: uuid.UUID,
) -> DeliveryAttempt:
    """Queue a new PENDING attempt for a FAILED (dead-letter) delivery."""
    stmt = (
        select(DeliveryAttempt)
        .where(DeliveryAttempt.id == attempt_id)
        .options(selectinload(DeliveryAttempt.endpoint))
    )
    result = await session.execute(stmt)
    attempt = result.scalar_one_or_none()
    if attempt is None or attempt.endpoint is None or attempt.endpoint.tenant_id != tenant_id:
        raise LookupError("Delivery attempt not found.")
    if attempt.status != DeliveryStatus.FAILED:
        raise ValueError("Only FAILED (dead-letter) attempts can be resent.")

    max_number = await session.scalar(
        select(func.max(DeliveryAttempt.attempt_number)).where(
            DeliveryAttempt.event_id == attempt.event_id,
            DeliveryAttempt.endpoint_id == attempt.endpoint_id,
        )
    )
    next_number = int(max_number or attempt.attempt_number) + 1

    replay = DeliveryAttempt(
        event_id=attempt.event_id,
        endpoint_id=attempt.endpoint_id,
        attempt_number=next_number,
        status=DeliveryStatus.PENDING,
    )
    session.add(replay)
    await session.commit()
    await session.refresh(replay)
    _schedule_deliveries([replay.id])
    return replay
