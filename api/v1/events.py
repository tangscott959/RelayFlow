"""Agent event ingest API."""

from __future__ import annotations

from fastapi import APIRouter, status

from api.deps import DbSession, RedisClient, TenantId
from schemas.event import EventIngestRequest, EventIngestResponse
from services.dispatcher import dispatch_event

router = APIRouter(prefix="/events", tags=["events"])


@router.post(
    "",
    response_model=EventIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest an Agent event and fan out webhook deliveries",
)
async def ingest_event(
    payload: EventIngestRequest,
    tenant_id: TenantId,
    session: DbSession,
    redis: RedisClient,
) -> EventIngestResponse:
    result = await dispatch_event(
        session=session,
        redis=redis,
        tenant_id=tenant_id,
        event_type=payload.event_type,
        idempotency_key=payload.idempotency_key,
        payload=payload.payload,
    )
    return EventIngestResponse(
        event_id=result.event_id,
        status="duplicate" if result.duplicate else "accepted",
        attempt_count=len(result.attempt_ids),
        attempt_ids=result.attempt_ids,
    )
