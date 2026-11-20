"""Pydantic v2 schemas for tenant registration and identity."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TenantCreate(BaseModel):
    """Public payload used to open a tenant workspace."""

    name: str = Field(min_length=1, max_length=128)

    @field_validator("name")
    @classmethod
    def strip_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name must not be blank.")
        return normalized


class TenantResponse(BaseModel):
    """Tenant identity without the secret API key."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    api_key_prefix: str
    created_at: datetime


class TenantCreateResponse(TenantResponse):
    """Create response that includes the plaintext API key exactly once."""

    api_key: str
