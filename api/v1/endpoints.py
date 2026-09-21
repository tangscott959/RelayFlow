"""Webhook endpoint registration and listing."""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import select

from api.deps import DbSession, TenantId
from models import WebhookEndpoint
from schemas.endpoint import EndpointCreate, EndpointResponse
from services.security import generate_endpoint_secret

router = APIRouter(prefix="/endpoints", tags=["endpoints"])


@router.post(
    "",
    response_model=EndpointResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a webhook endpoint",
)
async def create_endpoint(
    payload: EndpointCreate,
    tenant_id: TenantId,
    session: DbSession,
) -> WebhookEndpoint:
    endpoint = WebhookEndpoint(
        tenant_id=tenant_id,
        target_url=str(payload.target_url),
        secret_key=generate_endpoint_secret(),
        rate_limit_per_sec=payload.rate_limit_per_sec,
        subscribed_events=payload.subscribed_events,
    )
    session.add(endpoint)
    await session.commit()
    await session.refresh(endpoint)
    return endpoint


@router.get(
    "",
    response_model=list[EndpointResponse],
    summary="List webhook endpoints for the tenant",
)
async def list_endpoints(
    tenant_id: TenantId,
    session: DbSession,
) -> list[WebhookEndpoint]:
    stmt = (
        select(WebhookEndpoint)
        .where(WebhookEndpoint.tenant_id == tenant_id)
        .order_by(WebhookEndpoint.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
