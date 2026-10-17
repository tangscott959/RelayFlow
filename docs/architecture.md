# RelayFlow Architecture

Last updated: 2026-10-17

RelayFlow is a multi-tenant webhook gateway. Producers ingest events over HTTP; RelayFlow persists them once, queues outbound work, and delivers signed POSTs to subscriber URLs with retries and a dead-letter path so slow downstreams do not block upstream Agent or microservice pipelines.

This document describes **what is running today**, then **what the plan adds**.

## Tech stack

| Layer | Today | Planned |
| --- | --- | --- |
| HTTP API | FastAPI, Pydantic v2 | Tenant auth (Phase 4) |
| ORM / DB | SQLAlchemy 2.0 async, asyncpg, PostgreSQL 16 | Alembic migrations (Phase 4) |
| Queue / cache | Celery 5.3+, Redis 7 | Token-bucket keys in Redis (Phase 5) |
| Outbound HTTP | httpx, 5s timeout, Full Jitter backoff | Unchanged |
| Config | pydantic-settings, `.env` / `.env.example` | Unchanged |
| UI | None (OpenAPI at `/docs`) | Vite + React + TypeScript in `frontend/` (Phase 6) |
| Packaging | Docker Compose: web, **1** worker, postgres, redis | Extra `frontend` service; worker replicas + latency benchmarks (Phase 5) |

## Layered layout (today)

```
api/          HTTP routers and dependencies
core/         Settings and Redis client
db/           Async engine and session factory
models/       SQLAlchemy 2.0 ORM
schemas/      Pydantic v2 request/response models
services/     Signing and dispatch
workers/      Celery app and delivery task
main.py       FastAPI app, CORS, /health, /api mount
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
| `web` | uvicorn `main:app` | 8000 |
| `worker` | `celery -A workers.celery_app worker` | — |
| `postgres` | PostgreSQL 16 | 5432 |
| `redis` | Redis 7 | 6379 |

On web startup, `Base.metadata.create_all` creates tables. Celery uses a per-task async engine with `NullPool` so `asyncio.run` in the prefork worker does not share the FastAPI event loop.

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

### `webhook_endpoints`

Subscriber callback. `secret_key` is `whsec_...`. `subscribed_events` is JSONB (`"*"` matches all). Status: `active`, `paused`, `disabled`. `rate_limit_per_sec` is **stored, not enforced**.

### `webhook_events`

One row per ingest. Unique `(tenant_id, idempotency_key)`. `payload` is JSONB.

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

All v1 business routes require header `X-Tenant-ID` (UUID). Mounted at `/api`.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/health` | Liveness probe |
| POST | `/api/v1/endpoints` | Create endpoint, return `whsec_` secret |
| GET | `/api/v1/endpoints` | List tenant endpoints |
| POST | `/api/v1/events` | Ingest event, **202 Accepted** |
| GET | `/api/v1/endpoints/{endpoint_id}/deliveries` | Paginated delivery log |
| POST | `/api/v1/deliveries/{attempt_id}/resend` | Requeue a FAILED attempt |

## Ingest path (dispatcher)

Target: finish the request path within **15ms** (warning if exceeded).

1. Redis GET `relayflow:idempotency:{tenant_id}:{idempotency_key}` — duplicate short-circuit (TTL 24h).
2. Insert `webhook_events`. Unique-constraint races fall back to the existing row.
3. Load `ACTIVE` endpoints whose `subscribed_events` contain the `event_type` or `"*"`.
4. Insert `delivery_attempts` with `PENDING` and `attempt_number=1`.
5. Commit, then `SET` the Redis idempotency value to the `event_id`.
6. Publish `workers.delivery.deliver_webhook_task` via `celery_app.send_task` on a thread pool.

Phase 5 should reject or delay ingest/outbound here using a Redis token bucket keyed by tenant (and optionally endpoint).

## Delivery path (worker)

1. Load attempt + endpoint + event with `selectinload`.
2. Skip unless status is `PENDING`.
3. Sign body bytes: HMAC-SHA256 of `t={timestamp}.{payload}`.
4. POST with `httpx.Client(timeout=5.0)`:
   - `Content-Type: application/json`
   - `X-Agent-Timestamp: <unix>`
   - `X-Agent-Signature: v1=<hex>`
5. 2xx → `DELIVERED`.
6. Error or non-2xx → Full Jitter `random.uniform(0, min(300, 2**(attempt-1)))` seconds. If `attempt_number < 5`, mark `RETRYING` and enqueue the next attempt; otherwise `FAILED`.

Inbound verification parses `t=...,v1=...`, rejects timestamps outside 300 seconds, and uses `hmac.compare_digest`.

At-least-once: a crash after POST but before commit can duplicate a delivery.

## Configuration

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL DSN; rewritten to `postgresql+asyncpg://` |
| `REDIS_URL` | Redis 7; default Celery broker and result backend |
| `SECRET_KEY` | Application secret |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | Optional overrides |

Host processes use `.env` (from `.env.example`). Compose injects `postgres` / `redis` DNS names.

## Planned frontend (Phase 6)

Operator console in `frontend/`:

- Vite + React + TypeScript.
- Endpoints, ingest, delivery logs, DLQ resend against `/api/v1`.
- Compose service on port 5173, `/api` proxied to `web`.
- Until Phase 4, the UI may collect `X-Tenant-ID`.

## Known constraints

- Tenant identity is a request header, not authenticated tokens (Phase 4).
- Schema is `create_all`, not Alembic (Phase 4).
- No automated test suite (Phase 4).
- `rate_limit_per_sec` is unused; no tenant token bucket (Phase 5).
- Single Celery worker in Compose; no scale/latency benchmarks (Phase 5).
- No operator UI yet (Phase 6).
- CORS allows all origins without credentials.
- Automatic retries stop at five attempts; operators resend DLQ rows through the API.
