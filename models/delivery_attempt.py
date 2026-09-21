from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, CreatedAtMixin
from models.enums import DeliveryStatus

if TYPE_CHECKING:
    from models.webhook_endpoint import WebhookEndpoint
    from models.webhook_event import WebhookEvent


class DeliveryAttempt(CreatedAtMixin, Base):
    __tablename__ = "delivery_attempts"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "endpoint_id",
            "attempt_number",
            name="uq_delivery_attempts_event_endpoint_attempt",
        ),
        Index("ix_delivery_attempts_status_next_retry_at", "status", "next_retry_at"),
        Index("ix_delivery_attempts_endpoint_id", "endpoint_id"),
        Index("ix_delivery_attempts_event_id", "event_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("webhook_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("webhook_endpoints.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_headers: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(
            DeliveryStatus,
            name="delivery_status",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            native_enum=True,
            validate_strings=True,
        ),
        nullable=False,
        default=DeliveryStatus.PENDING,
        server_default=DeliveryStatus.PENDING.value,
        index=True,
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    event: Mapped[WebhookEvent] = relationship(back_populates="delivery_attempts")
    endpoint: Mapped[WebhookEndpoint] = relationship(back_populates="delivery_attempts")
