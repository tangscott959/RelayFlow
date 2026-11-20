"""Unit tests for the Redis token-bucket limiter."""

from __future__ import annotations

import uuid

import pytest

from services.rate_limit import (
    BucketState,
    RateLimitExceeded,
    apply_token_bucket,
    endpoint_bucket_key,
    ingest_bucket_key,
    try_acquire,
)
from tests.fakes import InMemoryRedis


def test_full_bucket_allows_then_denies_burst() -> None:
    start = BucketState(tokens=2.0, ts_ms=1_000_000)
    after_first, first = apply_token_bucket(
        start,
        capacity=2.0,
        refill_per_sec=2.0,
        now_ms=1_000_000,
    )
    assert first.allowed is True
    assert after_first.tokens == pytest.approx(1.0)

    after_second, second = apply_token_bucket(
        after_first,
        capacity=2.0,
        refill_per_sec=2.0,
        now_ms=1_000_000,
    )
    assert second.allowed is True

    _, third = apply_token_bucket(
        after_second,
        capacity=2.0,
        refill_per_sec=2.0,
        now_ms=1_000_000,
    )
    assert third.allowed is False
    assert third.retry_after >= 1


def test_tokens_refill_over_time_but_not_above_capacity() -> None:
    empty = BucketState(tokens=0.0, ts_ms=0)
    refilled, result = apply_token_bucket(
        empty,
        capacity=10.0,
        refill_per_sec=10.0,
        now_ms=2_000,
    )
    assert result.allowed is True
    assert refilled.tokens == pytest.approx(9.0)

    _, capped = apply_token_bucket(
        BucketState(tokens=10.0, ts_ms=0),
        capacity=10.0,
        refill_per_sec=10.0,
        now_ms=60_000,
        requested=0.0,
    )
    assert capped.remaining == pytest.approx(10.0)


def test_zero_capacity_is_always_denied() -> None:
    _, result = apply_token_bucket(
        BucketState(tokens=0.0, ts_ms=0),
        capacity=0.0,
        refill_per_sec=0.0,
        now_ms=1,
    )
    assert result.allowed is False
    assert result.retry_after == 60


def test_bucket_key_formats() -> None:
    tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    endpoint_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    assert ingest_bucket_key(tenant_id) == (
        "relayflow:ratelimit:ingest:00000000-0000-0000-0000-000000000001"
    )
    assert endpoint_bucket_key(endpoint_id) == (
        "relayflow:ratelimit:endpoint:00000000-0000-0000-0000-000000000002"
    )


async def test_try_acquire_persists_bucket_in_redis() -> None:
    redis = InMemoryRedis()
    key = "relayflow:ratelimit:ingest:test"
    first = await try_acquire(redis, key=key, rate_per_sec=1, now=1000.0)
    second = await try_acquire(redis, key=key, rate_per_sec=1, now=1000.0)
    assert first.allowed is True
    assert second.allowed is False
    assert second.retry_after >= 1
    assert key in redis.values


def test_rate_limit_exceeded_carries_retry_after() -> None:
    exc = RateLimitExceeded(retry_after=3, scope="ingest")
    assert exc.retry_after == 3
    assert exc.scope == "ingest"
