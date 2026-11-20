"""Redis token-bucket rate limiting for ingest and outbound delivery."""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass

from redis.asyncio import Redis

INGEST_BUCKET_PREFIX = "relayflow:ratelimit:ingest:"
ENDPOINT_BUCKET_PREFIX = "relayflow:ratelimit:endpoint:"
BUCKET_TTL_SECONDS: int = 60
ZERO_RATE_RETRY_AFTER_SECONDS: int = 60


class RateLimitExceeded(Exception):
    """Raised when an ingest request cannot take a token from the bucket."""

    def __init__(self, *, retry_after: int, scope: str) -> None:
        super().__init__(f"{scope} rate limit exceeded")
        self.retry_after = retry_after
        self.scope = scope


@dataclass(slots=True, frozen=True)
class BucketState:
    tokens: float
    ts_ms: int


@dataclass(slots=True, frozen=True)
class ConsumeResult:
    allowed: bool
    retry_after: int
    remaining: float


def ingest_bucket_key(tenant_id: uuid.UUID) -> str:
    return f"{INGEST_BUCKET_PREFIX}{tenant_id}"


def endpoint_bucket_key(endpoint_id: uuid.UUID) -> str:
    return f"{ENDPOINT_BUCKET_PREFIX}{endpoint_id}"


def encode_bucket_state(state: BucketState) -> str:
    return f"{state.tokens:.10f}:{state.ts_ms}"


def decode_bucket_state(raw: str) -> BucketState | None:
    if ":" not in raw:
        return None
    tokens_s, ts_s = raw.rsplit(":", 1)
    try:
        return BucketState(tokens=float(tokens_s), ts_ms=int(ts_s))
    except ValueError:
        return None


def apply_token_bucket(
    state: BucketState,
    *,
    capacity: float,
    refill_per_sec: float,
    now_ms: int,
    requested: float = 1.0,
) -> tuple[BucketState, ConsumeResult]:
    """Refill tokens then try to take ``requested`` from the bucket.

    Capacity and refill rate are both ``rate_limit_per_sec``: the bucket holds at
    most one second of burst and restores one token per ``1/rate`` seconds.
    """

    if capacity <= 0 or refill_per_sec <= 0:
        return state, ConsumeResult(
            allowed=False,
            retry_after=ZERO_RATE_RETRY_AFTER_SECONDS,
            remaining=0.0,
        )

    elapsed_seconds = max(0.0, (now_ms - state.ts_ms) / 1000.0)
    tokens = min(capacity, state.tokens + elapsed_seconds * refill_per_sec)
    refilled = BucketState(tokens=tokens, ts_ms=now_ms)

    if tokens >= requested:
        remaining = tokens - requested
        return BucketState(tokens=remaining, ts_ms=now_ms), ConsumeResult(
            allowed=True,
            retry_after=0,
            remaining=remaining,
        )

    deficit = requested - tokens
    retry_after = max(1, int(math.ceil(deficit / refill_per_sec)))
    return refilled, ConsumeResult(allowed=False, retry_after=retry_after, remaining=tokens)


async def try_acquire(
    redis: Redis,
    *,
    key: str,
    rate_per_sec: int,
    now: float | None = None,
) -> ConsumeResult:
    """Take one token from the Redis-backed bucket keyed by ``key``."""

    now_ms = int((time.time() if now is None else now) * 1000)
    if rate_per_sec <= 0:
        return ConsumeResult(
            allowed=False,
            retry_after=ZERO_RATE_RETRY_AFTER_SECONDS,
            remaining=0.0,
        )

    capacity = float(rate_per_sec)
    raw = await redis.get(key)
    if raw:
        state = decode_bucket_state(str(raw)) or BucketState(tokens=capacity, ts_ms=now_ms)
    else:
        state = BucketState(tokens=capacity, ts_ms=now_ms)

    new_state, result = apply_token_bucket(
        state,
        capacity=capacity,
        refill_per_sec=capacity,
        now_ms=now_ms,
        requested=1.0,
    )
    await redis.set(key, encode_bucket_state(new_state), ex=BUCKET_TTL_SECONDS)
    return result
