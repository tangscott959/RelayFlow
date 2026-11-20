# RelayFlow Architecture

Last updated: 2026-11-20

RelayFlow is a multi-tenant webhook gateway. Producers ingest events over HTTP; RelayFlow persists them once, queues outbound work, and delivers signed POSTs to subscriber URLs with retries and a dead-letter path so slow downstreams do not block upstream Agent or microservice pipelines.

This document describes **what is running today**, then **what the plan adds**.

## Tech stack

| Layer | Today | Planned |
| --- | --- | --- |
| HTTP API | FastAPI, Pydantic v2, Bearer API keys | Unchanged |
| ORM / DB | SQLAlchemy 2.0 async, asyncpg, PostgreSQL 16, Alembic | Unchanged |
| Queue / cache | Celery 5.3+, Redis 7, token-bucket keys, delivery metric counters | Worker replicas + benchmarks (Phase 5) |
| Outbound HTTP | httpx, 5s timeout, Full Jitter backoff | Unchanged |
| Config | pydantic-settings, `.env` / `.env.example` | Unchanged |
| UI | None (OpenAPI at `/docs`) | Vite + React + TypeScript in `frontend/` (Phase 6) |
| Packaging | Docker Compose: web, **1** worker, postgres, redis | Extra `frontend` service; worker replicas + latency benchmarks (Phase 5) |

## Layered layout (today)

```
api/          HTTP routers, dependencies, observability middleware
migrations/   Async Alembic env and revision scripts
core/         Settings, Redis, JSON logging, tracing, metrics
db/           Async engine and session factory
models/       SQLAlchemy 2.0 ORM
schemas/      Pydantic v2 request/response models
services/     Signing, tenant API keys, token bucket, and dispatch
tests/        pytest suite
workers/      Celery app and delivery task
main.py       FastAPI app, CORS, /health, /metrics, /api mount
docs/         develop_plan.md, architecture.md (committed)
```

Planned: `frontend/` for the operator console. The SPA must call `/api` only. Do not mix UI into Python packages, and do not use SQLAlchemy or Celery from the browser.

Routers use SQLAlchemy 2.0 `select()` / `AsyncSession` only. Services own transactions and fan-out. Workers must not import `services` package `__init__` in a way that pulls the dispatcher (circular import with `workers.delivery`).

**Not in git:** `.cursorrules`, `.cursor/`, `.env` / `.env.*`, `docs/changelog.md`. **In git:** `.env.example` (template, no secrets).

## Runtime topology (today)

```
Client  -->  FastAPI (web :8000)
                |  persist event + attempts
                |  Redis idempotency key
                v
            Celery broker (Redis)
                v
            Celery worker  (single replica)
                |  HMAC-SHA256 sign
                v
            Subscriber target_url (POST JSON)
```

| Service | Role | Port |
| --- | --- | --- |
| `web` | `alembic upgrade head` then uvicorn `main:app` | 8000 |
| `worker` | `celery -A workers.celery_app worker` | — |
| `postgres` | PostgreSQL 16 | 5432 |
| `redis` | Redis 7 | 6379 |

The `web` service applies Alembic migrations (`alembic upgrade head`, revision `0001_initial`) before uvicorn starts. FastAPI lifespan only disposes the engine and Redis client. Celery uses a per-task async engine with `NullPool` so `asyncio.run` in the prefork worker does not share the FastAPI event loop.

### Planned topology (Phases 5–6)

```
Browser (frontend :5173)  -->  /api proxy  -->  FastAPI
Producer / Agent          -->  FastAPI ingest (rate-limited)
                                    v
                              Celery + Redis
                                    v
                         N worker replicas  -->  subscribers
```

## Data model

### `tenants`

One workspace per customer. `api_key_hash` is SHA-256 of the secret `rfk_` key (unique). `api_key_prefix` is the first 12 characters, shown after create. The plaintext key is returned only from `POST /api/v1/tenants`.

### `webhook_endpoints`

Subscriber callback. `tenant_id` references `tenants.id`. `secret_key` is `whsec_...`. `subscribed_events` is JSONB (`"*"` matches all). Status: `active`, `paused`, `disabled`. `rate_limit_per_sec` is the outbound token-bucket rate.

### `webhook_events`

One row per ingest. `tenant_id` references `tenants.id`. Unique `(tenant_id, idempotency_key)`. `payload` is JSONB.

### `delivery_attempts`

One row per try. Unique `(event_id, endpoint_id, attempt_number)`.

| Status | Meaning |
| --- | --- |
| `pending` | Queued, not yet POSTed |
| `retrying` | Failed; a later attempt was scheduled |
| `delivered` | HTTP 2xx |
| `failed` | Dead letter (max 5 automatic tries, or missing relations) |

Manual resend of `failed` inserts a new `pending` row with `attempt_number = max + 1` and enqueues it.

## HTTP API (today)

Mounted at `/api`. `POST /api/v1/tenants` is public. All other v1 business routes require `Authorization: Bearer <rfk_...>`. Tenant identity is derived from the hashed key, not a client-supplied id.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/health` | Liveness probe |
| GET | `/metrics` | Prometheus text (HTTP, ingest, delivery) |
| POST | `/api/v1/tenants` | Create tenant, return `rfk_` API key once |
| GET | `/api/v1/tenants/me` | Current tenant (no secret) |
| POST | `/api/v1/endpoints` | Create endpoint, return `whsec_` secret |
| GET | `/api/v1/endpoints` | List tenant endpoints (`?status=`) |
| GET | `/api/v1/endpoints/{endpoint_id}` | Get one endpoint |
| PATCH | `/api/v1/endpoints/{endpoint_id}` | Update URL, subscriptions, rate limit, or `active`/`paused`/`disabled` |
| POST | `/api/v1/events` | Ingest event, **202 Accepted** |
| GET | `/api/v1/endpoints/{endpoint_id}/deliveries` | Paginated delivery log (`?status=`) |
| POST | `/api/v1/deliveries/{attempt_id}/resend` | Requeue a FAILED attempt |

## Ingest path (dispatcher)

Target: finish the request path within **15ms** (warning and `relayflow_ingest_over_budget_total` if exceeded).

1. Redis GET `relayflow:idempotency:{tenant_id}:{idempotency_key}` — duplicate short-circuit (TTL 24h). Duplicates do not consume ingest tokens.
2. Take one token from `relayflow:ratelimit:ingest:{tenant_id}` (capacity = `INGEST_RATE_LIMIT_PER_SEC`). If empty, raise 429 with `Retry-After`.
3. Insert `webhook_events`. Unique-constraint races fall back to the existing row.
4. Load `ACTIVE` endpoints whose `subscribed_events` contain the `event_type` or `"*"`. `paused` and `disabled` endpoints are skipped for new events.
5. Insert `delivery_attempts` with `PENDING` and `attempt_number=1`.
6. Commit, then `SET` the Redis idempotency value to the `event_id`.
7. Publish `workers.delivery.deliver_webhook_task` via `celery_app.send_task` on a thread pool, passing the request `trace_id`.

## Delivery path (worker)

1. Load attempt + endpoint + event with `selectinload`.
2. Skip unless status is `PENDING`.
3. If the endpoint is `paused`, defer the same PENDING attempt (~30s) without consuming a retry. If `disabled`, mark the attempt `FAILED`.
4. Take one token from `relayflow:ratelimit:endpoint:{endpoint_id}` using `rate_limit_per_sec`. If empty, keep `PENDING`, set `next_retry_at`, and re-enqueue the **same** attempt (does not count toward the five automatic tries).
5. Sign body bytes: HMAC-SHA256 of `t={timestamp}.{payload}`.
6. POST with `httpx.Client(timeout=5.0)`:
   - `Content-Type: application/json`
   - `X-Agent-Timestamp: <unix>`
   - `X-Agent-Signature: v1=<hex>`
7. 2xx → `DELIVERED`.
8. Error or non-2xx → Full Jitter `random.uniform(0, min(300, 2**(attempt-1)))` seconds. If `attempt_number < 5`, mark `RETRYING` and enqueue the next attempt; otherwise `FAILED`.

Inbound verification parses `t=...,v1=...`, rejects timestamps outside 300 seconds, and uses `hmac.compare_digest`.

At-least-once: a crash after POST but before commit can duplicate a delivery.

JSON logs include `request_id`, `trace_id`, and `tenant_id` when bound. Responses echo `X-Request-ID` and `X-Trace-Id` (from `X-Request-ID` / W3C `traceparent`, or generated). Delivery workers increment Redis keys `relayflow:metrics:delivery:{outcome}` so `GET /metrics` can scrape every replica.

## Configuration

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL DSN; rewritten to `postgresql+asyncpg://` |
| `REDIS_URL` | Redis 7; default Celery broker and result backend |
| `SECRET_KEY` | Application secret |
| `INGEST_RATE_LIMIT_PER_SEC` | Per-tenant ingest token bucket (default 50/s) |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | Optional overrides |

Host processes use `.env` (from `.env.example`). Compose injects `postgres` / `redis` DNS names.

## Planned frontend (Phase 6)

Operator console in `frontend/`:

- Vite + React + TypeScript.
- Endpoints, ingest, delivery logs, DLQ resend against `/api/v1`.
- Compose service on port 5173, `/api` proxied to `web`.
- The UI stores the tenant API key and sends `Authorization: Bearer`.

## Known constraints

- pytest covers HMAC signing, idempotency, Full Jitter / DLQ, API contracts, and API-key auth. Cases marked `integration` skip when PostgreSQL or Redis is not reachable.
- Single Celery worker in Compose; no scale/latency benchmarks (Phase 5).
- No operator UI yet (Phase 6).
- CORS allows all origins without credentials.
- Automatic retries stop at five attempts; operators resend DLQ rows through the API.
