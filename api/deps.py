"""Shared FastAPI dependencies for the HTTP API."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from core.redis import get_redis
from core.tracing import set_tenant_id
from db.session import get_async_session
from models import Tenant
from services.tenants import API_KEY_PREFIX, resolve_tenant_by_api_key

_bearer = HTTPBearer(
    auto_error=False,
    description="Tenant API key issued at registration (prefix rfk_).",
)

DbSession = Annotated[AsyncSession, Depends(get_async_session)]
RedisClient = Annotated[Redis, Depends(get_redis)]


async def get_current_tenant(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Tenant:
    """Resolve the caller from ``Authorization: Bearer <rfk_...>``."""

    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid API key.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not credentials.credentials:
        raise unauthorized
    raw_key = credentials.credentials.strip()
    if not raw_key.startswith(API_KEY_PREFIX):
        raise unauthorized
    tenant = await resolve_tenant_by_api_key(session=session, raw_key=raw_key)
    if tenant is None:
        raise unauthorized
    set_tenant_id(str(tenant.id))
    return tenant


async def get_current_tenant_id(tenant: Annotated[Tenant, Depends(get_current_tenant)]) -> uuid.UUID:
    return tenant.id


CurrentTenant = Annotated[Tenant, Depends(get_current_tenant)]
TenantId = Annotated[uuid.UUID, Depends(get_current_tenant_id)]
