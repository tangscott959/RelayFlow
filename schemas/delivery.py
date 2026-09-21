"""Pydantic v2 schemas for delivery attempt logs and pagination."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from models.enums import DeliveryStatus


class DeliveryAttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    endpoint_id: uuid.UUID
    attempt_number: int
    http_status: int | None
    response_headers: dict[str, Any] | None
    response_body: str | None
    duration_ms: int | None
    status: DeliveryStatus
    next_retry_at: datetime | None
    created_at: datetime


class PaginatedDeliveryAttemptResponse(BaseModel):
    """Page of delivery attempts for a single endpoint."""

    items: list[DeliveryAttemptResponse]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
