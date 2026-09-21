"""Pydantic v2 schemas for webhook endpoint create and read operations."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator

from models.enums import EndpointStatus


class EndpointCreate(BaseModel):
    """Incoming payload for registering a subscriber endpoint."""

    target_url: AnyHttpUrl
    subscribed_events: list[str] = Field(default_factory=list)
    rate_limit_per_sec: int = Field(default=10, ge=0, le=10_000)

    @field_validator("subscribed_events")
    @classmethod
    def normalize_subscribed_events(cls, value: list[str]) -> list[str]:
        events: list[str] = []
        seen: set[str] = set()
        for item in value:
            event_type = item.strip()
            if not event_type or event_type in seen:
                continue
            seen.add(event_type)
            events.append(event_type)
        return events


class EndpointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    target_url: str
    secret_key: str
    rate_limit_per_sec: int
    subscribed_events: list[str]
    status: EndpointStatus
    created_at: datetime
