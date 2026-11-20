# RelayFlow Development Plan

Last updated: 2026-11-20

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

**Phases 0–3 are done.** The ingest → queue → signed POST → retry / DLQ spine runs locally in Docker (web, one worker, PostgreSQL 16, Redis 7). **Phase 4 is in progress:** Alembic replaces `create_all`, and HMAC signing has unit tests.

**Not done yet (relative to the product intent):** remaining API/idempotency/retry tests, real tenant auth, token-bucket limiting, multi-worker scale tests, and the operator UI.

**Next recommended work:** finish Phase 4 (API/idempotency/retry tests, then tenant credentials). Phase 6 (console) can start against `/api/v1` with `X-Tenant-ID` if we want UI earlier; prefer it after Phase 4 if the console should use real credentials.

---

## Phase overview

| Phase | Goal | Status |
| --- | --- | --- |
| 0 | Local project rules and git workflow | Done (rules stay on this machine) |
| 1 | Config, async DB session, core ORM models | Done |
| 2 | HMAC signing + Celery delivery worker | Done |
| 3 | HTTP API, dispatcher, Docker Compose | Done |
| 4 | Alembic migrations, automated tests, tenant auth | In progress (Alembic + signing tests) |
| 5 | Token-bucket rate limiting, observability, scale benchmarks | Not started |
| 6 | Operator console (Vite + React + TypeScript) | Not started |

### Mapping to the original description

| Intent | Today |
| --- | --- |
| FastAPI REST, ingest decoupled from delivery | Built (`POST /api/v1/events` → 202, Celery) |
| Celery + Redis queue and cache | Built (broker, result backend, idempotency keys) |
| PostgreSQL delivery state + DLQ | Built (`delivery_attempts`, `FAILED` + resend API) |
| At-least-once + jittered exponential backoff | Built (Full Jitter, max 5 automatic tries) |
| Docker | Built (one web, **one** worker) |
| HMAC signing (Svix / Stripe style) | Built (`whsec_`, `X-Agent-Signature`) |
| Per-tenant token-bucket rate limiting | **Not built** (`rate_limit_per_sec` is stored only) |
| Horizontal worker scale + latency benchmarks | **Not built** |
| Operator console | **Planned (Phase 6)** |
| Real multi-tenant auth | **Planned (Phase 4)**; API uses `X-Tenant-ID` |

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

### Phase 4 — Hardening (in progress)

- **Done:** Alembic instead of `create_all` on startup. Compose `web` runs `alembic upgrade head` before uvicorn. Scripts live in `migrations/` (not `alembic/`, which would shadow the Alembic package under `PYTHONPATH=/app`). Initial revision `0001_initial` creates the three tables and PostgreSQL enums.
- **Done:** HMAC signing unit tests (`tests/test_security.py`).
- **Next:** tests for idempotency, retry/DLQ, and API contracts.
- **Next:** replace header-only `X-Tenant-ID` with tenant credentials (tokens or equivalent).

### Phase 5 — Rate limiting, ops, scale (later)

- Redis **token bucket** per tenant (and/or per endpoint using `rate_limit_per_sec`).
- Metrics, structured logs, tracing.
- Pause/disable endpoint APIs, richer delivery filters.
- Compose/k8s **worker replicas > 1** and throughput benchmarks under injected latency.

### Phase 6 — Operator console (planned)

Vite + React + TypeScript in `frontend/` (never mixed into Python packages). Talks to FastAPI `/api` only — no SQLAlchemy or Celery in the browser.

Screens:

- Endpoint list / create (show `whsec_` once).
- Event ingest form and 202 result.
- Paginated delivery log.
- DLQ resend for `FAILED` attempts.

Integration: Compose service `frontend` (port 5173) proxying `/api` to `web`. MVP may send `X-Tenant-ID` until Phase 4 auth exists. Strict TypeScript, functional components, browser-verified flows.

---

## Progress log

Newest first. Also append local `docs/changelog.md` (gitignored). Update [architecture.md](./architecture.md) when layout or data flow changes.

### 2026-11-20

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
