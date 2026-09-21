# RelayFlow

Multi-tenant webhook relay for Agent events. Ingest once, fan out to subscriber endpoints with HMAC-SHA256 signatures, retries, and a dead-letter path.

## Status

Phases 1–3 are complete: async data model, signed Celery delivery, HTTP API, and Docker Compose. Schema is created on API startup (`create_all`); Alembic migrations and tenant auth are next.

## Stack

Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0 async (asyncpg), PostgreSQL 16, Redis 7, Celery 5.3+.

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

| Service | URL |
| --- | --- |
| API | http://localhost:8000 |
| OpenAPI docs | http://localhost:8000/docs |
| Health | http://localhost:8000/health |

Business routes require header `X-Tenant-ID` (UUID).

## API

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | Liveness probe |
| POST | `/api/v1/endpoints` | Create a subscriber endpoint (`whsec_` signing secret) |
| GET | `/api/v1/endpoints` | List endpoints for the tenant |
| POST | `/api/v1/events` | Ingest an event (**202 Accepted**) |
| GET | `/api/v1/endpoints/{endpoint_id}/deliveries` | Paginated delivery log |
| POST | `/api/v1/deliveries/{attempt_id}/resend` | Requeue a `FAILED` (dead-letter) attempt |

Example ingest:

```bash
curl -X POST http://localhost:8000/api/v1/events \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: 00000000-0000-0000-0000-000000000001" \
  -d "{\"event_type\":\"agent.completed\",\"idempotency_key\":\"evt-1\",\"payload\":{\"ok\":true}}"
```

Matching `ACTIVE` endpoints receive a POST with:

- `Content-Type: application/json`
- `X-Agent-Timestamp: <unix>`
- `X-Agent-Signature: v1=<hmac-sha256>`

Failed deliveries retry up to 5 times with Full Jitter backoff, then move to `FAILED`.

## Layout

```
api/          HTTP routers
core/         Settings and Redis
db/           Async SQLAlchemy session
models/       ORM
schemas/      Pydantic v2
services/     Signing and dispatch
workers/      Celery delivery task
docs/         Architecture and development plan
```

## Configuration

Copy `.env.example`. Compose injects `postgres` / `redis` hostnames; local uvicorn/Celery on the host should use `localhost` as in the example file.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL DSN (`postgresql+asyncpg://...`) |
| `REDIS_URL` | Redis; default Celery broker and result backend |
| `SECRET_KEY` | Application secret |

## Documentation

- [Architecture](docs/architecture.md)
- [Development plan](docs/develop_plan.md)

New product work lands on `feature/<short-kebab-name>` and merges to `main` through a pull request.
