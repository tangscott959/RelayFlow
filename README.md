# RelayFlow

Multi-tenant webhook relay for Agent events. Ingest once, fan out to subscriber endpoints with HMAC-SHA256 signatures, retries, and a dead-letter path.

## Status

Phases 1–4 are complete. Phase 5 is in progress: token-bucket limiting, endpoint pause/disable, and observability (`GET /metrics`, JSON logs, trace ids). Worker-scale benchmarks and the operator console remain. See the [development plan](docs/develop_plan.md).

## Stack

**Backend:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0 async (asyncpg), PostgreSQL 16, Redis 7, Celery 5.3+.

**Frontend (planned):** Vite, React, TypeScript — operator console in `frontend/` for endpoints, event ingest, delivery logs, and dead-letter resend.

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

The `web` service runs `alembic upgrade head` before uvicorn. If you already used an older stack that created tables with `create_all`, reset the volume (`docker compose down -v`) or stamp the current revision:

```bash
docker compose exec web alembic stamp head
```

Run tests. HMAC and HTTP contract tests run anywhere. Cases marked `integration` need PostgreSQL and Redis (the Compose service network). If a local Postgres already occupies port 5432, run the suite inside `web`:

```bash
pip install -r requirements.txt
pytest
docker compose exec web pytest
```

| Service | URL |
| --- | --- |
| API | http://localhost:8000 |
| OpenAPI docs | http://localhost:8000/docs |
| Health | http://localhost:8000/health |
| Metrics | http://localhost:8000/metrics |

Register a tenant to receive an `rfk_` API key (shown once). Business routes require `Authorization: Bearer <api_key>`.

## API

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | Liveness probe |
| GET | `/metrics` | Prometheus metrics (HTTP, ingest, delivery) |
| POST | `/api/v1/tenants` | Create a tenant and return the API key once |
| GET | `/api/v1/tenants/me` | Current tenant (prefix only, never the secret) |
| POST | `/api/v1/endpoints` | Create a subscriber endpoint (`whsec_` signing secret) |
| GET | `/api/v1/endpoints` | List endpoints (`?status=` optional) |
| GET | `/api/v1/endpoints/{endpoint_id}` | Get one endpoint |
| PATCH | `/api/v1/endpoints/{endpoint_id}` | Update URL, subscriptions, rate limit, or status (`active` / `paused` / `disabled`) |
| POST | `/api/v1/events` | Ingest an event (**202 Accepted**) |
| GET | `/api/v1/endpoints/{endpoint_id}/deliveries` | Paginated delivery log (`?status=` optional) |
| POST | `/api/v1/deliveries/{attempt_id}/resend` | Requeue a `FAILED` (dead-letter) attempt |

Example:

```bash
curl -s -X POST http://localhost:8000/api/v1/tenants \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"acme\"}"

curl -X POST http://localhost:8000/api/v1/events \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer rfk_YOUR_KEY" \
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
migrations/   Alembic revision scripts
core/         Settings, Redis, logging, metrics
db/           Async SQLAlchemy session
models/       ORM
schemas/      Pydantic v2
services/     Signing and dispatch
tests/        pytest suite
workers/      Celery delivery task
frontend/     Planned operator console (React + TypeScript)
docs/         Architecture and development plan
```

## Configuration

Copy `.env.example`. Compose injects `postgres` / `redis` hostnames; local uvicorn/Celery on the host should use `localhost` as in the example file.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL DSN (`postgresql+asyncpg://...`) |
| `REDIS_URL` | Redis; default Celery broker and result backend |
| `SECRET_KEY` | Application secret |
| `INGEST_RATE_LIMIT_PER_SEC` | Per-tenant ingest token bucket (default 50/s) |

## Documentation

- [Architecture](docs/architecture.md)
- [Development plan](docs/develop_plan.md)

New product work lands on `feature/<short-kebab-name>` and merges to `main` through a pull request.
