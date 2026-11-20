"""Tenant registration and identity."""

from __future__ import annotations

from fastapi import APIRouter, status

from api.deps import CurrentTenant, DbSession
from models import Tenant
from schemas.tenant import TenantCreate, TenantCreateResponse, TenantResponse
from services.tenants import create_tenant

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post(
    "",
    response_model=TenantCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a tenant and return its API key once",
)
async def register_tenant(payload: TenantCreate, session: DbSession) -> TenantCreateResponse:
    created = await create_tenant(session=session, name=payload.name)
    return TenantCreateResponse(
        id=created.tenant.id,
        name=created.tenant.name,
        api_key=created.api_key,
        api_key_prefix=created.tenant.api_key_prefix,
        created_at=created.tenant.created_at,
    )


@router.get(
    "/me",
    response_model=TenantResponse,
    summary="Return the tenant bound to the presented API key",
)
async def read_current_tenant(tenant: CurrentTenant) -> Tenant:
    return tenant
