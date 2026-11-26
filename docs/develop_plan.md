# RelayFlow Development Plan

Last updated: 2026-11-26

## Product intent

RelayFlow is a high-throughput, fault-tolerant webhook gateway (Webhook-as-a-Service) for distributed microservices and long-running Agent / AI workflows, in the same family as Svix and Stripe Webhooks.

The contract we are building toward:

1. Decouple ingest from outbound delivery so slow or failing subscribers cannot block upstream.
2. Accept events over a low-latency FastAPI REST API (**202 Accepted**).
3. Queue work asynchronously with **Celery + Redis**.
4. Persist delivery state and a Dead Letter Queue in **PostgreSQL**.
5. Enforce **per-tenant token-bucket** rate limiting (ingest and/or outbound).
6. Guarantee **at-least-once** delivery with **jittered exponential backoff**.
7. Run **containerized** (Docker Compose today; more replicas later).
8. Provide an **operator console** (React + TypeScript) so the product is usable without curl.
9. **Benchmark** horizontal worker scaling under simulated network latency.

---

## Current status

**Phases 0–6 are done.** The operator console is in `frontend/` (Compose service on port 5173).

**Not done yet (relative to the product intent):** none of the original contract items remain.

**Next recommended work:** polish the console from operator feedback, or extra ops (auth hardening, hosted Prometheus).

---

## Phase overview

| Phase | Goal | Status |
| --- | --- | --- |
| 0 | Local project rules and git workflow | Done (rules stay on this machine) |
| 1 | Config, async DB session, core ORM models | Done |
| 2 | HMAC signing + Celery delivery worker | Done |
| 3 | HTTP API, dispatcher, Docker Compose | Done |
| 4 | Alembic migrations, automated tests, tenant auth | Done |
| 5 | Token-bucket rate limiting, observability, scale benchmarks | Done |
| 6 | Operator console (Vite + React + TypeScript) | Done |

### Mapping to the original description

| Intent | Today |
| --- | --- |
| FastAPI REST, ingest decoupled from delivery | Built (`POST /api/v1/events` → 202, Celery) |
| Celery + Redis queue and cache | Built (broker, result backend, idempotency keys) |
| PostgreSQL delivery state + DLQ | Built (`delivery_attempts`, `FAILED` + resend API) |
| At-least-once + jittered exponential backoff | Built (Full Jitter, max 5 automatic tries) |
| Docker | Built (one web, **scalable** Celery workers) |
| HMAC signing (Svix / Stripe style) | Built (`whsec_`, `X-Agent-Signature`) |
| Per-tenant token-bucket rate limiting | Built (ingest 429; outbound defer using `rate_limit_per_sec`) |
| Horizontal worker scale + latency benchmarks | Built (`--scale worker=N`, delayed sink, `docs/benchmarks.md`) |
| Operator console | Built (`frontend/`, Compose `:5173`, Bearer API key) |
| Real multi-tenant auth | Built (`POST /api/v1/tenants`, `Authorization: Bearer rfk_...`) |
| Observability | Built (JSON logs, `X-Request-ID` / `X-Trace-Id`, `GET /metrics`) |

---

## Phase details

### Phase 0 — Project rules (done)

- Backend: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0 async, Celery 5.3+, Redis 7, PostgreSQL 16.
- Frontend (planned): Vite + React + TypeScript in `frontend/`.
- Git: implement on `feature/<short-kebab-name>` (or `chore/<name>` for tiny non-product work), then PR into `main`.
- Published docs: `docs/develop_plan.md`, `docs/architecture.md`. Local-only: `.cursorrules`, `.cursor/`, `.env` / `.env.*`, `docs/changelog.md`, class proposal PDF and architecture diagram images. Keep `.env.example` in git.

### Phase 1 — Foundation (done)

- Pinned `requirements.txt`.
- `core/config.py` from `.env` (`DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`).
- `db/session.py`: `create_async_engine` + `AsyncSession`.
- Models: `webhook_endpoints`, `webhook_events`, `delivery_attempts`.

### Phase 2 — Security and delivery worker (done)

- HMAC-SHA256 over `t={timestamp}.{payload}`; verify with a 300s window and `hmac.compare_digest`.
- Celery JSON + UTC; Redis broker/backend.
- Worker POST via `httpx.Client(timeout=5.0)`; Full Jitter backoff; dead-letter `FAILED`.

### Phase 3 — API and local orchestration (done)

- Schemas for endpoints, ingest, paginated deliveries.
- Dispatcher: Redis idempotency, persist event, match `ACTIVE` subscribers (`event_type` or `*`), enqueue tasks (15ms budget).
- REST under `/api/v1`, plus `/health`.
- Multi-stage `Dockerfile` and Compose: `web`, `worker`, `postgres`, `redis`.

### Phase 4 — Hardening (done)

- Alembic instead of `create_all` on startup. Compose `web` runs `alembic upgrade head` before uvicorn. Scripts live in `migrations/` (not `alembic/`, which would shadow the Alembic package under `PYTHONPATH=/app`). Revisions `0001_initial` and `0002_tenants`.
- HMAC signing, idempotency, retry/DLQ, and API contract tests. Integration cases skip when PostgreSQL or Redis is not running.
- Tenant credentials: `POST /api/v1/tenants` returns an `rfk_` API key once; business routes use `Authorization: Bearer`. Keys are stored as SHA-256 hashes. `X-Tenant-ID` is no longer accepted.

### Phase 5 — Rate limiting, ops, scale (done)

- **Done:** Redis token bucket. Ingest is limited per tenant (`INGEST_RATE_LIMIT_PER_SEC`, default 50/s) with **429** and `Retry-After`. Outbound delivery is limited per endpoint (`rate_limit_per_sec`); a dry bucket defers the same PENDING attempt and does not count toward the five automatic tries.
- **Done:** Pause/disable/resume via `PATCH /api/v1/endpoints/{id}` (`active` / `paused` / `disabled`). List endpoints and delivery logs accept `?status=`. Queued deliveries on a paused endpoint are deferred; disabled endpoints fail in-flight attempts.
- **Done:** JSON structured logs, request/trace correlation (`X-Request-ID`, `X-Trace-Id`, W3C `traceparent`), and Prometheus `GET /metrics` (HTTP, ingest budget, delivery outcomes in Redis).
- **Done:** Compose worker replicas (`docker compose up --scale worker=N`, Celery `--concurrency 1`). Delayed sink + `python -m benchmarks.run` under injected latency; see [benchmarks.md](./benchmarks.md).

### Phase 6 — Operator console (done)

Vite + React + TypeScript in `frontend/` (never mixed into Python packages). Talks to FastAPI `/api` only — no SQLAlchemy or Celery in the browser.

Screens:

- Workspace sign-in: create a tenant or paste an `rfk_` key (plaintext key shown once).
- Endpoint list / create (show `whsec_` once), pause / resume / disable.
- Event ingest form and 202 result (including duplicates and 429).
- Paginated delivery log with status filter.
- DLQ resend for `FAILED` attempts.

Integration: Compose service `frontend` (port 5173) proxying `/api` to `web`. The console stores the tenant API key in `localStorage` and sends `Authorization: Bearer`. Strict TypeScript, functional components, browser-verified flows.

---

## Progress log

Newest first. Also append local `docs/changelog.md` (gitignored). Update [architecture.md](./architecture.md) when layout or data flow changes.

### 2026-11-26

- Named the solo author (Xingxuan Tang) in `README.md`.

### 2026-11-20

- Added the Vite + React operator console (`frontend/`, Compose `:5173`).
- Added Compose worker replicas and latency benchmarks (`benchmarks/`, `docs/benchmarks.md`).
- Added JSON logs, request/trace correlation, and Prometheus `GET /metrics` (HTTP, ingest, delivery).
- Added endpoint lifecycle APIs (`GET`/`PATCH`, pause/disable) and delivery `?status=` filters.
- Started Phase 5: Redis token-bucket ingest (per tenant, 429) and outbound delivery (per endpoint `rate_limit_per_sec`, deferred retry).
- Replaced `X-Tenant-ID` with tenant API keys (`rfk_`, SHA-256 at rest, `Authorization: Bearer`) and Alembic revision `0002_tenants`.
- Added pytest coverage for Redis/DB idempotency, Full Jitter retry and DLQ threshold, and API contracts (422 validation, 202 ingest, pagination, resend 409/202).
- Started Phase 4: Alembic async migrations (`migrations/` + `0001_initial`), removed `create_all` from FastAPI lifespan, Compose applies `alembic upgrade head` before uvicorn.
- Added pytest and HMAC signing unit tests.

### 2026-10-17

- Keep class proposal PDF and architecture diagram images local (gitignored); submit them outside the repo.
- Aligned `docs/develop_plan.md` and `docs/architecture.md` with the current product intent, built spine, and Phases 4–6.
- Stopped tracking `.cursorrules` and `.cursor/` on GitHub; ignore real env files; keep `.env.example`.
- Scheduled Phase 6: React + TypeScript operator console.

### 2026-09-21

- README, feature-branch workflow, `docs/` created. `docs/changelog.md` is local-only.

### 2026-09-15

- Docker Compose stack started; worker circular import fixed.

### 2026-09-14

- Phases 0–3 implemented (rules, models, signing/worker, API + Docker).
