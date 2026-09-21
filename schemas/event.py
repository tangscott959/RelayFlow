"""Pydantic v2 schemas for Agent event ingestion."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class EventIngestRequest(BaseModel):
    """Inbound Agent event accepted by the ingest API."""

    event_type: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=255)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_type", "idempotency_key")
    @classmethod
    def strip_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value must not be blank.")
        return normalized


class EventIngestResponse(BaseModel):
    """202 Accepted body returned after enqueueing deliveries."""

    event_id: uuid.UUID
    status: Literal["accepted", "duplicate"]
    attempt_count: int
    attempt_ids: list[uuid.UUID]
