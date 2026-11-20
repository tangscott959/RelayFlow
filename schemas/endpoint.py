"""Pydantic v2 schemas for webhook endpoint create and read operations."""

from __future__ import annotations

import uuid
from datetime import datetime

from typing import Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

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


class EndpointUpdate(BaseModel):
    """Partial update for an existing subscriber endpoint."""

    target_url: AnyHttpUrl | None = None
    subscribed_events: list[str] | None = None
    rate_limit_per_sec: int | None = Field(default=None, ge=0, le=10_000)
    status: EndpointStatus | None = None

    @field_validator("subscribed_events")
    @classmethod
    def normalize_subscribed_events(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return EndpointCreate.normalize_subscribed_events(value)

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> Self:
        if (
            self.target_url is None
            and self.subscribed_events is None
            and self.rate_limit_per_sec is None
            and self.status is None
        ):
            raise ValueError("At least one field is required.")
        return self


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
