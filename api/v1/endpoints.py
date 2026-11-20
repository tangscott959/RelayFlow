"""Webhook endpoint registration, listing, and lifecycle updates."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from api.deps import DbSession, TenantId
from models import WebhookEndpoint
from models.enums import EndpointStatus
from schemas.endpoint import EndpointCreate, EndpointResponse, EndpointUpdate
from services.security import generate_endpoint_secret

router = APIRouter(prefix="/endpoints", tags=["endpoints"])


async def _load_owned_endpoint(
    session: DbSession,
    tenant_id: uuid.UUID,
    endpoint_id: uuid.UUID,
) -> WebhookEndpoint:
    stmt = select(WebhookEndpoint).where(
        WebhookEndpoint.id == endpoint_id,
        WebhookEndpoint.tenant_id == tenant_id,
    )
    endpoint = (await session.execute(stmt)).scalar_one_or_none()
    if endpoint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found.")
    return endpoint


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
    endpoint_status: EndpointStatus | None = Query(default=None, alias="status"),
) -> list[WebhookEndpoint]:
    stmt = select(WebhookEndpoint).where(WebhookEndpoint.tenant_id == tenant_id)
    if endpoint_status is not None:
        stmt = stmt.where(WebhookEndpoint.status == endpoint_status)
    stmt = stmt.order_by(WebhookEndpoint.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get(
    "/{endpoint_id}",
    response_model=EndpointResponse,
    summary="Get one webhook endpoint",
)
async def get_endpoint(
    endpoint_id: uuid.UUID,
    tenant_id: TenantId,
    session: DbSession,
) -> WebhookEndpoint:
    return await _load_owned_endpoint(session, tenant_id, endpoint_id)


@router.patch(
    "/{endpoint_id}",
    response_model=EndpointResponse,
    summary="Update endpoint URL, subscriptions, rate limit, or status",
)
async def update_endpoint(
    endpoint_id: uuid.UUID,
    payload: EndpointUpdate,
    tenant_id: TenantId,
    session: DbSession,
) -> WebhookEndpoint:
    endpoint = await _load_owned_endpoint(session, tenant_id, endpoint_id)
    if payload.target_url is not None:
        endpoint.target_url = str(payload.target_url)
    if payload.subscribed_events is not None:
        endpoint.subscribed_events = payload.subscribed_events
    if payload.rate_limit_per_sec is not None:
        endpoint.rate_limit_per_sec = payload.rate_limit_per_sec
    if payload.status is not None:
        endpoint.status = payload.status
    await session.commit()
    await session.refresh(endpoint)
    return endpoint
