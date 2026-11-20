"""Delivery logs and dead-letter resend."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from api.deps import DbSession, TenantId
from models import DeliveryAttempt, WebhookEndpoint
from models.enums import DeliveryStatus
from schemas.delivery import DeliveryAttemptResponse, PaginatedDeliveryAttemptResponse
from services.dispatcher import resend_dead_letter

router = APIRouter(tags=["deliveries"])


@router.get(
    "/endpoints/{endpoint_id}/deliveries",
    response_model=PaginatedDeliveryAttemptResponse,
    summary="Page through delivery attempts for an endpoint",
)
async def list_endpoint_deliveries(
    endpoint_id: uuid.UUID,
    tenant_id: TenantId,
    session: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    attempt_status: DeliveryStatus | None = Query(default=None, alias="status"),
) -> PaginatedDeliveryAttemptResponse:
    endpoint_stmt = select(WebhookEndpoint).where(
        WebhookEndpoint.id == endpoint_id,
        WebhookEndpoint.tenant_id == tenant_id,
    )
    endpoint = (await session.execute(endpoint_stmt)).scalar_one_or_none()
    if endpoint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found.")

    filters = [DeliveryAttempt.endpoint_id == endpoint_id]
    if attempt_status is not None:
        filters.append(DeliveryAttempt.status == attempt_status)

    total = (
        await session.scalar(
            select(func.count()).select_from(DeliveryAttempt).where(*filters)
        )
        or 0
    )

    stmt = (
        select(DeliveryAttempt)
        .where(*filters)
        .order_by(DeliveryAttempt.created_at.desc(), DeliveryAttempt.attempt_number.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return PaginatedDeliveryAttemptResponse(
        items=[DeliveryAttemptResponse.model_validate(row) for row in rows],
        total=int(total),
        page=page,
        page_size=page_size,
    )


@router.post(
    "/deliveries/{attempt_id}/resend",
    response_model=DeliveryAttemptResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Manually requeue a dead-letter (FAILED) delivery attempt",
)
async def resend_delivery(
    attempt_id: uuid.UUID,
    tenant_id: TenantId,
    session: DbSession,
) -> DeliveryAttempt:
    try:
        return await resend_dead_letter(
            session=session,
            tenant_id=tenant_id,
            attempt_id=attempt_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
