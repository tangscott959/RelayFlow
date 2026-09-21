from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Enum, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, CreatedAtMixin
from models.enums import EndpointStatus

if TYPE_CHECKING:
    from models.delivery_attempt import DeliveryAttempt


class WebhookEndpoint(CreatedAtMixin, Base):
    __tablename__ = "webhook_endpoints"
    __table_args__ = (
        CheckConstraint(
            "rate_limit_per_sec >= 0",
            name="ck_webhook_endpoints_rate_limit_non_negative",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    secret_key: Mapped[str] = mapped_column(String(255), nullable=False)
    rate_limit_per_sec: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=10,
        server_default="10",
    )
    subscribed_events: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    status: Mapped[EndpointStatus] = mapped_column(
        Enum(
            EndpointStatus,
            name="endpoint_status",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            native_enum=True,
            validate_strings=True,
        ),
        nullable=False,
        default=EndpointStatus.ACTIVE,
        server_default=EndpointStatus.ACTIVE.value,
        index=True,
    )

    delivery_attempts: Mapped[list[DeliveryAttempt]] = relationship(
        back_populates="endpoint",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
