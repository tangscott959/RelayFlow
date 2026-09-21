# RelayFlow Architecture

Last updated: 2026-09-21

RelayFlow is a multi-tenant webhook relay. Agent events are accepted over HTTP, persisted once (idempotently), and delivered to subscriber endpoints with HMAC signatures, retries, and a dead-letter path.

## Tech stack

| Layer | Choice |
| --- | --- |
| Language | Python 3.11+ |
| HTTP | FastAPI |
| Validation | Pydantic v2 |
| ORM | SQLAlchemy 2.0 async (`select()`, `AsyncSession`, `DeclarativeBase`) |
| Database | PostgreSQL 16 via asyncpg |
| Cache / broker | Redis 7 |
| Jobs | Celery 5.3+ (JSON, UTC) |
| Outbound HTTP | httpx, 5s timeout, Full Jitter exponential backoff |
| Config | pydantic-settings from `.env` |

## Layered layout

```
api/          HTTP routers and dependencies
core/         Settings and Redis client
db/           Async engine and session factory
models/       SQLAlchemy 2.0 ORM
schemas/      Pydantic v2 request/response models
services/     Domain logic (signing, dispatch)
workers/      Celery app and delivery task
main.py       FastAPI app, CORS, /health, /api mount
```

Routers must not talk to the database with legacy Query APIs. Services own transactions and fan-out. Workers must not import `services` package `__init__` in a way that pulls the dispatcher (avoids a circular import with `workers.delivery`).

## Runtime topology

```
Client  -->  FastAPI (web :8000)
                |  persist event + attempts
                |  Redis idempotency key
                v
            Celery broker (Redis)
                v
            Celery worker
                |  HMAC-SHA256 sign
                v
            Subscriber target_url (POST JSON)
```

Docker Compose runs four processes:

| Service | Role | Port |
| --- | --- | --- |
| `web` | uvicorn `main:app` | 8000 |
| `worker` | `celery -A workers.celery_app worker` | — |
| `postgres` | PostgreSQL 16 | 5432 |
| `redis` | Redis 7 | 6379 |

On web startup, `Base.metadata.create_all` creates tables. Celery uses a per-task async engine with `NullPool` so `asyncio.run` in the prefork worker does not share the FastAPI event loop.

## Data model

### `webhook_endpoints`

Subscriber callback. `secret_key` is generated as `whsec_...`. `subscribed_events` is a JSONB list of event types; `"*"` matches all types. Status: `active`, `paused`, `disabled`.

### `webhook_events`

One row per ingest. Unique `(tenant_id, idempotency_key)`. `payload` is JSONB.

### `delivery_attempts`

One row per try to a given endpoint. Unique `(event_id, endpoint_id, attempt_number)`. Status:

| Status | Meaning |
| --- | --- |
| `pending` | Queued, not yet POSTed |
| `retrying` | Failed; a later attempt was scheduled |
| `delivered` | HTTP 2xx |
| `failed` | Dead letter (max 5 automatic tries, or missing relations) |

Manual resend of a `failed` row inserts a new `pending` attempt with `attempt_number = max + 1` and enqueues it.

## HTTP API

All v1 business routes require header `X-Tenant-ID` (UUID). Routes are mounted at `/api`.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/health` | Liveness probe |
| POST | `/api/v1/endpoints` | Create endpoint, return `whsec_` secret |
| GET | `/api/v1/endpoints` | List tenant endpoints |
| POST | `/api/v1/events` | Ingest event, **202 Accepted** |
| GET | `/api/v1/endpoints/{endpoint_id}/deliveries` | Paginated delivery log |
| POST | `/api/v1/deliveries/{attempt_id}/resend` | Requeue a FAILED attempt |

## Ingest path (dispatcher)

Target: finish the request path within **15ms** (log a warning if exceeded).

1. Redis GET `relayflow:idempotency:{tenant_id}:{idempotency_key}` — duplicate short-circuit (TTL 24h).
2. Insert `webhook_events`. Unique-constraint races fall back to the existing row.
3. Load `ACTIVE` endpoints whose `subscribed_events` contain the `event_type` or `"*"`.
4. Insert `delivery_attempts` with `PENDING` and `attempt_number=1`.
5. Commit, then `SET` the Redis idempotency value to the `event_id`.
6. Publish `workers.delivery.deliver_webhook_task` via `celery_app.send_task` on a thread pool (does not block the event loop).

## Delivery path (worker)

1. Load attempt + endpoint + event with SQLAlchemy 2.0 `selectinload`.
2. Skip unless status is `PENDING`.
3. Sign body bytes: HMAC-SHA256 of `t={timestamp}.{payload}`.
4. POST with `httpx.Client(timeout=5.0)` and headers:
   - `Content-Type: application/json`
   - `X-Agent-Timestamp: <unix>`
   - `X-Agent-Signature: v1=<hex>`
5. 2xx → `DELIVERED` (store status, duration, headers, truncated body).
6. Network error or non-2xx → Full Jitter delay `random.uniform(0, min(300, 2**(attempt-1)))` seconds. If `attempt_number < 5`, mark current row `RETRYING` and enqueue the next attempt. Otherwise mark `FAILED`.

Inbound verification (for subscribers, or future receive-side use) parses `t=...,v1=...`, rejects timestamps outside 300 seconds, and compares with `hmac.compare_digest`.

## Configuration

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL DSN; `postgres://` / `postgresql://` is rewritten to `postgresql+asyncpg://` |
| `REDIS_URL` | Redis 7; also the default Celery broker and result backend |
| `SECRET_KEY` | Application secret |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | Optional overrides |

Local host development uses `.env` (see `.env.example`). Compose injects service DNS (`postgres`, `redis`) so containers do not use `localhost`.

## Known constraints

- Tenant identity is a request header, not authenticated tokens.
- Schema is created with `create_all`, not Alembic.
- CORS allows all origins without credentials.
- Automatic retries stop at five attempts; operators resend DLQ rows through the API.
