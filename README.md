# RelayFlow

Multi-tenant webhook relay for Agent events. Ingest once, fan out to subscriber endpoints with HMAC-SHA256 signatures, retries, and a dead-letter path.

## Status

Phases 1–6 are complete. The operator console is at http://localhost:5173. See the [development plan](docs/develop_plan.md).

## Stack

**Backend:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0 async (asyncpg), PostgreSQL 16, Redis 7, Celery 5.3+.

**Frontend:** Vite, React, TypeScript — operator console in `frontend/` for endpoints, event ingest, delivery logs, and dead-letter resend.

## Quick start

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine + Compose). Then:

```bash
git clone https://github.com/tangscott959/RelayFlow.git
cd RelayFlow
docker compose up --build
```

Compose does not need a `.env` file. Wait until http://localhost:8000/health returns `{"status":"ok",...}`, then either:

**Console (easiest):** open http://localhost:5173 → Create tenant → Endpoints → Ingest → Deliveries.

**curl:** copy `api_key` from the first response (`rfk_...`). `subscribed_events` must include `"*"` or the event type, or nothing is delivered.

```bash
curl -s -X POST http://localhost:8000/api/v1/tenants \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"acme\"}"

curl -s -X POST http://localhost:8000/api/v1/endpoints \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer rfk_YOUR_KEY" \
  -d "{\"target_url\":\"https://example.com/hooks\",\"subscribed_events\":[\"*\"]}"

curl -s -X POST http://localhost:8000/api/v1/events \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer rfk_YOUR_KEY" \
  -d "{\"event_type\":\"agent.completed\",\"idempotency_key\":\"evt-1\",\"payload\":{\"ok\":true}}"
```

`https://example.com/hooks` returns 405, so deliveries go `retrying` then `FAILED`. That is expected. Use a [webhook.site](https://webhook.site) URL if you want `DELIVERED` and the HMAC headers.

Scale workers:

```bash
docker compose up -d --scale worker=3
```

The `web` service runs `alembic upgrade head` before uvicorn. If an older volume was created with `create_all`, reset it (`docker compose down -v`) or stamp:

```bash
docker compose exec web alembic stamp head
```

On Windows, a host Postgres on port 5432 can hide the Compose database. Prefer tests inside the container:

```bash
docker compose exec web pytest
```

Host tests (HMAC / HTTP contracts only, unless you point `.env` at a real Postgres and Redis):

```bash
cp .env.example .env
pip install -r requirements.txt
pytest
```

| Service | URL |
| --- | --- |
| API | http://localhost:8000 |
| OpenAPI docs | http://localhost:8000/docs |
| Health | http://localhost:8000/health |
| Metrics | http://localhost:8000/metrics |
| Bench sink (profile `bench`) | http://localhost:8089/health |
| Operator console | http://localhost:5173 |

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

A full tenant → endpoint → ingest sequence is in Quick start.

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
benchmarks/   Delayed sink and scale-out runner
frontend/     Operator console (React + TypeScript)
docs/         Architecture, development plan, benchmarks
```

## Configuration

Copy `.env.example`. Compose injects `postgres` / `redis` hostnames; local uvicorn/Celery on the host should use `localhost` as in the example file.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL DSN (`postgresql+asyncpg://...`) |
| `REDIS_URL` | Redis; default Celery broker and result backend |
| `SECRET_KEY` | Application secret |
| `INGEST_RATE_LIMIT_PER_SEC` | Per-tenant ingest token bucket (default 50/s) |
| `SINK_DELAY_MS` | Injected delay for the optional bench sink (default 200) |

## Documentation

- [Architecture](docs/architecture.md)
- [Development plan](docs/develop_plan.md)
- [Worker-scale benchmarks](docs/benchmarks.md)

New product work lands on `feature/<short-kebab-name>` and merges to `main` through a pull request.
