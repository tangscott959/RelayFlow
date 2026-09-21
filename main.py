"""RelayFlow HTTP application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.v1.router import api_router
from core.config import settings
from core.redis import close_redis
from db.session import engine
from models import Base


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Create ORM tables on boot and dispose pooled connections on shutdown."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
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

app.include_router(api_router, prefix="/api")


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    """Liveness probe used by Docker Compose and orchestrators."""
    return {"status": "ok", "service": settings.app_name}
