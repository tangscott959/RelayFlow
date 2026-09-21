"""Async Redis client used for idempotency keys and Celery coordination."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from redis.asyncio import Redis

from core.config import settings

redis_client: Redis = Redis.from_url(
    settings.redis_url,
    encoding="utf-8",
    decode_responses=True,
)


async def get_redis() -> AsyncGenerator[Redis, None]:
    """Yield the shared async Redis client for FastAPI dependencies."""
    yield redis_client


async def close_redis() -> None:
    """Close the shared Redis connection on application shutdown."""
    await redis_client.aclose()
