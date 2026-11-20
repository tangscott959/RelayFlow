"""Shared pytest fixtures. Environment defaults are set before app imports."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

# Compose injects DATABASE_URL/REDIS_URL (host ``postgres`` / ``redis``). Keep
# those when present. Host pytest without env falls back to localhost.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://relayflow:relayflow@localhost:5432/relayflow",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-insecure-secret")
os.environ.setdefault("DEBUG", "false")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from tests.fakes import InMemoryRedis


@pytest.fixture
def tenant_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def tenant_headers(tenant_id: uuid.UUID) -> dict[str, str]:
    return {"X-Tenant-ID": str(tenant_id)}


@pytest.fixture
def memory_redis() -> InMemoryRedis:
    return InMemoryRedis()


@pytest.fixture
def asgi_app():
    from main import app

    yield app
    app.dependency_overrides.clear()


@pytest.fixture
async def contract_client(asgi_app) -> AsyncIterator[AsyncClient]:
    """HTTP client that never opens PostgreSQL or Redis."""

    from core.redis import get_redis
    from db.session import get_async_session

    async def _session() -> AsyncIterator[object]:
        yield object()

    async def _redis() -> AsyncIterator[object]:
        yield object()

    asgi_app.dependency_overrides[get_async_session] = _session
    asgi_app.dependency_overrides[get_redis] = _redis
    async with AsyncClient(
        transport=ASGITransport(app=asgi_app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
async def require_backend() -> None:
    """Skip the test when local PostgreSQL or Redis is not reachable."""

    from core.redis import redis_client
    from db.session import engine

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")

    try:
        await redis_client.ping()
    except Exception as exc:
        pytest.skip(f"Redis is not available: {exc}")


@pytest.fixture
async def api_client(
    asgi_app,
    require_backend: None,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    """In-process API client against the real database, without Celery fan-out."""

    monkeypatch.setattr("services.dispatcher._schedule_deliveries", lambda attempt_ids: None)
    async with AsyncClient(
        transport=ASGITransport(app=asgi_app),
        base_url="http://test",
    ) as client:
        yield client
