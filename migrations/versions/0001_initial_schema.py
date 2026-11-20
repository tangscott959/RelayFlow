"""Initial RelayFlow schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-20

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

endpoint_status = postgresql.ENUM(
    "active",
    "paused",
    "disabled",
    name="endpoint_status",
    create_type=False,
)
delivery_status = postgresql.ENUM(
    "pending",
    "delivered",
    "failed",
    "retrying",
    name="delivery_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM("active", "paused", "disabled", name="endpoint_status").create(
        bind,
        checkfirst=True,
    )
    postgresql.ENUM("pending", "delivered", "failed", "retrying", name="delivery_status").create(
        bind,
        checkfirst=True,
    )

    op.create_table(
        "webhook_endpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_url", sa.String(length=2048), nullable=False),
        sa.Column("secret_key", sa.String(length=255), nullable=False),
        sa.Column("rate_limit_per_sec", sa.Integer(), server_default="10", nullable=False),
        sa.Column(
            "subscribed_events",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", endpoint_status, server_default="active", nullable=False),
        sa.CheckConstraint(
            "rate_limit_per_sec >= 0",
            name="ck_webhook_endpoints_rate_limit_non_negative",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_webhook_endpoints_status"),
        "webhook_endpoints",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_webhook_endpoints_tenant_id"),
        "webhook_endpoints",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_webhook_events_tenant_idempotency"),
    )
    op.create_index(
        op.f("ix_webhook_events_event_type"),
        "webhook_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_webhook_events_tenant_id"),
        "webhook_events",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "delivery_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("endpoint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("response_headers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", delivery_status, server_default="pending", nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["endpoint_id"], ["webhook_endpoints.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["webhook_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_id",
            "endpoint_id",
            "attempt_number",
            name="uq_delivery_attempts_event_endpoint_attempt",
        ),
    )
    op.create_index(
        "ix_delivery_attempts_status_next_retry_at",
        "delivery_attempts",
        ["status", "next_retry_at"],
        unique=False,
    )
    op.create_index(
        "ix_delivery_attempts_endpoint_id",
        "delivery_attempts",
        ["endpoint_id"],
        unique=False,
    )
    op.create_index(
        "ix_delivery_attempts_event_id",
        "delivery_attempts",
        ["event_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_delivery_attempts_status"),
        "delivery_attempts",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_delivery_attempts_status"), table_name="delivery_attempts")
    op.drop_index("ix_delivery_attempts_event_id", table_name="delivery_attempts")
    op.drop_index("ix_delivery_attempts_endpoint_id", table_name="delivery_attempts")
    op.drop_index("ix_delivery_attempts_status_next_retry_at", table_name="delivery_attempts")
    op.drop_table("delivery_attempts")

    op.drop_index(op.f("ix_webhook_events_tenant_id"), table_name="webhook_events")
    op.drop_index(op.f("ix_webhook_events_event_type"), table_name="webhook_events")
    op.drop_table("webhook_events")

    op.drop_index(op.f("ix_webhook_endpoints_tenant_id"), table_name="webhook_endpoints")
    op.drop_index(op.f("ix_webhook_endpoints_status"), table_name="webhook_endpoints")
    op.drop_table("webhook_endpoints")

    bind = op.get_bind()
    postgresql.ENUM(name="delivery_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="endpoint_status").drop(bind, checkfirst=True)
