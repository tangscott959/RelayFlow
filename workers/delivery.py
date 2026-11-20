"""Celery worker that delivers signed webhook payloads to subscriber endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import threading
import time
import uuid
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar

import httpx
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import NullPool

from core.config import settings
from models import DeliveryAttempt, DeliveryStatus, EndpointStatus, WebhookEndpoint, WebhookEvent
from services.rate_limit import endpoint_bucket_key, try_acquire
from services.security import generate_signature
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)

MAX_DELIVERY_ATTEMPTS: int = 5
BASE_BACKOFF_SECONDS: float = 1.0
MAX_BACKOFF_SECONDS: float = 300.0
MAX_RESPONSE_BODY_CHARS: int = 16_384
PAUSED_ENDPOINT_DEFER_SECONDS: float = 30.0

T = TypeVar("T")


def should_move_to_dead_letter(attempt_number: int) -> bool:
    """Return True when automatic retries are exhausted (DLQ / FAILED)."""

    return attempt_number >= MAX_DELIVERY_ATTEMPTS


def compute_full_jitter_delay(attempt_number: int) -> float:
    """Return a Full Jitter delay in seconds for the given attempt number.

    Formula: ``sleep = random.uniform(0, min(cap, base * 2 ** (attempt - 1)))``.
    """
    exponential_ceiling = min(
        MAX_BACKOFF_SECONDS,
        BASE_BACKOFF_SECONDS * (2 ** max(attempt_number - 1, 0)),
    )
    return random.uniform(0.0, exponential_ceiling)


def serialize_payload(payload: Any) -> bytes:
    """Serialize event JSON so the signed bytes match the HTTP body exactly."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _truncate_body(body: str | None) -> str | None:
    if body is None:
        return None
    if len(body) <= MAX_RESPONSE_BODY_CHARS:
        return body
    return body[:MAX_RESPONSE_BODY_CHARS]


def post_webhook(target_url: str, secret: str, payload_bytes: bytes) -> dict[str, Any]:
    """POST the signed payload with a 5s timeout. Never raises to the caller."""
    timestamp = int(time.time())
    signature = generate_signature(secret, payload_bytes, timestamp)
    headers = {
        "Content-Type": "application/json",
        "X-Agent-Timestamp": str(timestamp),
        "X-Agent-Signature": f"v1={signature}",
    }
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(target_url, content=payload_bytes, headers=headers)
        duration_ms = int((time.perf_counter() - started) * 1000)
        return {
            "http_status": response.status_code,
            "response_headers": dict(response.headers),
            "response_body": _truncate_body(response.text),
            "duration_ms": duration_ms,
            "succeeded": 200 <= response.status_code < 300,
        }
    except httpx.HTTPError as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.warning("Webhook POST failed for %s: %s", target_url, exc)
        return {
            "http_status": None,
            "response_headers": None,
            "response_body": _truncate_body(str(exc)),
            "duration_ms": duration_ms,
            "succeeded": False,
        }


@asynccontextmanager
async def worker_session() -> AsyncIterator[AsyncSession]:
    """Create a loop-local async engine so Celery's asyncio.run() stays isolated.

    Celery prefork workers are synchronous. Each task spins a fresh event loop via
    ``asyncio.run``. Sharing the FastAPI engine across loops causes
    ``Future attached to a different loop`` errors, so the worker uses NullPool
    and disposes the engine when the task finishes.
    """
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        poolclass=NullPool,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    try:
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Bridge Celery's sync process to SQLAlchemy async sessions."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    # A loop is already running (gevent / nested call). asyncio.run() cannot
    # nest, so the coroutine is executed on a dedicated thread and loop.
    result: T | None = None
    error: BaseException | None = None

    def _runner() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(coro)
        except BaseException as exc:
            error = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if error is not None:
        raise error
    return result  # type: ignore[return-value]


async def _load_attempt(session: AsyncSession, attempt_id: uuid.UUID) -> DeliveryAttempt | None:
    stmt = (
        select(DeliveryAttempt)
        .where(DeliveryAttempt.id == attempt_id)
        .options(
            selectinload(DeliveryAttempt.endpoint),
            selectinload(DeliveryAttempt.event),
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _defer_pending_attempt(
    session: AsyncSession,
    attempt: DeliveryAttempt,
    delay_seconds: float,
    reason: str,
) -> None:
    """Requeue the same PENDING attempt without consuming a retry toward the DLQ."""

    delay_seconds = float(max(delay_seconds, 1.0))
    attempt.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
    await session.commit()
    deliver_webhook_task.apply_async(args=[str(attempt.id)], countdown=delay_seconds)
    logger.info(
        "Deferred attempt %s (%s); retry in %.2fs",
        attempt.id,
        reason,
        delay_seconds,
    )


async def _defer_rate_limited_attempt(
    session: AsyncSession,
    attempt: DeliveryAttempt,
    retry_after: int,
) -> None:
    await _defer_pending_attempt(session, attempt, float(retry_after), "endpoint rate limit")


async def _schedule_retry(
    session: AsyncSession,
    attempt: DeliveryAttempt,
) -> None:
    delay_seconds = compute_full_jitter_delay(attempt.attempt_number)
    next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)

    attempt.status = DeliveryStatus.RETRYING
    attempt.next_retry_at = next_retry_at

    next_attempt = DeliveryAttempt(
        event_id=attempt.event_id,
        endpoint_id=attempt.endpoint_id,
        attempt_number=attempt.attempt_number + 1,
        status=DeliveryStatus.PENDING,
        next_retry_at=next_retry_at,
    )
    session.add(next_attempt)
    await session.flush()
    next_attempt_id = str(next_attempt.id)
    await session.commit()

    deliver_webhook_task.apply_async(
        args=[next_attempt_id],
        countdown=delay_seconds,
    )
    logger.info(
        "Scheduled retry attempt %s for event %s in %.2fs",
        next_attempt_id,
        attempt.event_id,
        delay_seconds,
    )


async def _deliver_webhook(attempt_id: str) -> None:
    try:
        attempt_uuid = uuid.UUID(attempt_id)
    except ValueError:
        logger.error("Invalid delivery attempt id: %s", attempt_id)
        return

    async with worker_session() as session:
        attempt = await _load_attempt(session, attempt_uuid)
        if attempt is None:
            logger.error("DeliveryAttempt %s not found", attempt_id)
            return
        if attempt.status != DeliveryStatus.PENDING:
            logger.info(
                "Skipping DeliveryAttempt %s with status %s",
                attempt_id,
                attempt.status,
            )
            return

        endpoint: WebhookEndpoint | None = attempt.endpoint
        event: WebhookEvent | None = attempt.event
        if endpoint is None or event is None:
            attempt.status = DeliveryStatus.FAILED
            attempt.response_body = "Missing related endpoint or event"
            await session.commit()
            logger.error("DeliveryAttempt %s is missing endpoint or event", attempt_id)
            return

        if endpoint.status == EndpointStatus.PAUSED:
            await _defer_pending_attempt(
                session,
                attempt,
                PAUSED_ENDPOINT_DEFER_SECONDS,
                "endpoint paused",
            )
            return
        if endpoint.status == EndpointStatus.DISABLED:
            attempt.status = DeliveryStatus.FAILED
            attempt.response_body = "Endpoint is disabled"
            await session.commit()
            logger.warning("DeliveryAttempt %s dropped; endpoint is disabled", attempt_id)
            return

        rate_redis = Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        try:
            outbound_limit = await try_acquire(
                rate_redis,
                key=endpoint_bucket_key(endpoint.id),
                rate_per_sec=endpoint.rate_limit_per_sec,
            )
        finally:
            await rate_redis.aclose()

        if not outbound_limit.allowed:
            await _defer_rate_limited_attempt(session, attempt, outbound_limit.retry_after)
            return

        payload_bytes = serialize_payload(event.payload)
        outcome = await asyncio.to_thread(
            post_webhook,
            endpoint.target_url,
            endpoint.secret_key,
            payload_bytes,
        )

        attempt.http_status = outcome["http_status"]
        attempt.response_headers = outcome["response_headers"]
        attempt.response_body = outcome["response_body"]
        attempt.duration_ms = outcome["duration_ms"]

        if outcome["succeeded"]:
            attempt.status = DeliveryStatus.DELIVERED
            attempt.next_retry_at = None
            await session.commit()
            logger.info(
                "Delivered attempt %s to %s (%s) in %sms",
                attempt_id,
                endpoint.target_url,
                attempt.http_status,
                attempt.duration_ms,
            )
            return

        if should_move_to_dead_letter(attempt.attempt_number):
            attempt.status = DeliveryStatus.FAILED
            attempt.next_retry_at = None
            await session.commit()
            logger.warning(
                "DeliveryAttempt %s exhausted %s tries; moved to dead-letter FAILED",
                attempt_id,
                MAX_DELIVERY_ATTEMPTS,
            )
            return

        await _schedule_retry(session, attempt)


@celery_app.task(name="workers.delivery.deliver_webhook_task")
def deliver_webhook_task(attempt_id: str) -> None:
    """Deliver one webhook attempt and retry with Full Jitter backoff on failure."""
    run_async(_deliver_webhook(attempt_id))
