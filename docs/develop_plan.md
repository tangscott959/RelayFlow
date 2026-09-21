# RelayFlow Development Plan

Last updated: 2026-09-21

## Current status

**Phases 1–3 are complete.** RelayFlow can ingest Agent events, fan out signed webhook deliveries, retry with Full Jitter, and run locally via Docker Compose (web, worker, PostgreSQL 16, Redis 7).

The live stack was started on 2026-09-15. A circular import between `services` and `workers` was fixed so the Celery worker stays up.

**Next recommended work:** Phase 4 (Alembic migrations, automated tests, and request authentication).

---

## Phase overview

| Phase | Goal | Status |
| --- | --- | --- |
| 0 | Project rules (`.cursorrules`) | Done |
| 1 | Foundation: config, async DB session, core ORM models | Done |
| 2 | HMAC signing + Celery delivery worker | Done |
| 3 | HTTP API, dispatcher, Docker Compose | Done |
| 4 | Migrations, tests, tenant auth | Not started |
| 5 | Rate limiting, observability, DLQ UI / ops APIs | Not started |

---

## Phase details

### Phase 0 — Project rules

- Backend stack locked: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0 async, Celery 5.3+, Redis 7, PostgreSQL 16.
- Layered layout: `api/`, `core/`, `db/`, `models/`, `schemas/`, `services/`, `workers/`.
- Comments, docstrings, and documentation must be written in professional English.
- Git workflow: new features land on `feature/<name>` and merge to `main` via pull request.

### Phase 1 — Foundation (done)

- Pinned `requirements.txt`.
- `core/config.py` loads `.env` (`DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`).
- `db/session.py` provides `create_async_engine` and `AsyncSession`.
- Models: `webhook_endpoints`, `webhook_events`, `delivery_attempts`.

### Phase 2 — Security and delivery worker (done)

- `services/security.py`: HMAC-SHA256 (`t={timestamp}.{payload}`), replay window, `hmac.compare_digest`.
- `workers/celery_app.py`: Redis broker/backend, JSON serializer, UTC.
- `workers/delivery.py`: POST with `httpx.Client(timeout=5.0)`, signed headers, up to 5 attempts, Full Jitter backoff, dead-letter `FAILED`.

### Phase 3 — API and local orchestration (done)

- Pydantic v2 schemas for endpoints, ingest, and paginated deliveries.
- `services/dispatcher.py`: Redis idempotency, persist event, match `ACTIVE` subscribers, enqueue Celery tasks (15ms budget).
- REST under `/api/v1` plus `/health`.
- Multi-stage `Dockerfile` and `docker-compose.yml` (web, worker, postgres, redis).

### Phase 4 — Hardening (next)

- Alembic migrations instead of `create_all` on startup.
- Automated tests for signing, dispatcher idempotency, retry/DLQ, and API contracts.
- Replace header-only `X-Tenant-ID` with real tenant authentication.

### Phase 5 — Productization (later)

- Per-endpoint rate limiting (`rate_limit_per_sec`).
- Metrics, structured logs, tracing.
- Endpoint pause/disable APIs, delivery filters, webhook payload replay tooling.

---

## Progress log

Keep this section as a running record. Newest entries first. When new code ships, append a bullet here **and** a dated entry in local `docs/changelog.md` (gitignored, not published). Update [architecture.md](./architecture.md) if structure or data flow changes.

### 2026-09-21

- Added `README.md` (quick start, API table, layout).
- Added feature-branch workflow: implement on `feature/<name>`, merge to `main` when done (`.cursor/rules/git-branching.mdc`).
- Added `docs/` (`develop_plan.md`, `architecture.md`) and a Cursor rule that requires documenting new work.
- Added `.gitignore`; `docs/changelog.md` is local-only and will not be pushed to GitHub.

### 2026-09-15

- Started Docker Desktop and `docker compose up --build`.
- Fixed circular import: `services/__init__.py` no longer imports the dispatcher; enqueue uses `celery_app.send_task(...)`.
- Web `/health` returned OK; Celery registered `workers.delivery.deliver_webhook_task`.

### 2026-09-14

- Phase 3: API, dispatcher, Docker.
- Phase 2: signing module and delivery worker. Delivery success status is `DELIVERED`.
- Phase 1: config, async session, three core models.
- Phase 0: `.cursorrules`.
