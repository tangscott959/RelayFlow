"""Shared FastAPI dependencies for the HTTP API."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from core.redis import get_redis
from db.session import get_async_session

TenantId = Annotated[uuid.UUID, Header(alias="X-Tenant-ID")]
DbSession = Annotated[AsyncSession, Depends(get_async_session)]
RedisClient = Annotated[Redis, Depends(get_redis)]
