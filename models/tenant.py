from __future__ import annotations

import uuid

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, CreatedAtMixin


class Tenant(CreatedAtMixin, Base):
    """A customer workspace authenticated by a hashed API key."""

    __tablename__ = "tenants"
    __table_args__ = (UniqueConstraint("api_key_hash", name="uq_tenants_api_key_hash"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    api_key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
