"""RelayFlow HTTP application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from api.deps import RedisClient
from api.middleware import ObservabilityMiddleware
from api.v1.router import api_router
from core.config import settings
from core.logging import configure_logging
from core.metrics import render_delivery_metrics, render_process_metrics, render_prometheus
from core.redis import close_redis
from db.session import engine

configure_logging()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Dispose pooled connections and the Redis client on shutdown.

    Schema changes are applied by Alembic (`alembic upgrade head`) before the
    API process starts, not via ``create_all`` here.
    """
    yield
    await engine.dispose()
    await close_redis()


app = FastAPI(
    title=settings.app_name,
    description="Multi-tenant webhook relay for Agent events.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ObservabilityMiddleware)

app.include_router(api_router, prefix="/api")


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    """Liveness probe used by Docker Compose and orchestrators."""
    return {"status": "ok", "service": settings.app_name}


@app.get("/metrics", tags=["ops"])
async def metrics(redis: RedisClient) -> PlainTextResponse:
    """Prometheus text exposition of HTTP, ingest, and delivery counters."""

    body = render_prometheus(
        render_process_metrics(),
        await render_delivery_metrics(redis),
    )
    return PlainTextResponse(
        content=body,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
