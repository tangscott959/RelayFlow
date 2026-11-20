"""Add tenants and API-key credentials.

Revision ID: 0002_tenants
Revises: 0001_initial
Create Date: 2026-11-20

"""

from __future__ import annotations

import hashlib
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_tenants"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("api_key_hash", sa.String(length=64), nullable=False),
        sa.Column("api_key_prefix", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("api_key_hash", name="uq_tenants_api_key_hash"),
    )

    bind = op.get_bind()
    existing = bind.execute(
        sa.text(
            """
            SELECT DISTINCT tenant_id FROM webhook_endpoints
            UNION
            SELECT DISTINCT tenant_id FROM webhook_events
            """
        )
    ).fetchall()
    for (tenant_id,) in existing:
        digest = hashlib.sha256(str(tenant_id).encode("utf-8")).hexdigest()
        bind.execute(
            sa.text(
                """
                INSERT INTO tenants (id, name, api_key_hash, api_key_prefix)
                VALUES (:id, :name, :api_key_hash, :api_key_prefix)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": tenant_id,
                "name": "legacy-tenant",
                "api_key_hash": digest,
                "api_key_prefix": "rfk_legacy",
            },
        )

    op.create_foreign_key(
        "fk_webhook_endpoints_tenant_id_tenants",
        "webhook_endpoints",
        "tenants",
        ["tenant_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_webhook_events_tenant_id_tenants",
        "webhook_events",
        "tenants",
        ["tenant_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_webhook_events_tenant_id_tenants", "webhook_events", type_="foreignkey")
    op.drop_constraint(
        "fk_webhook_endpoints_tenant_id_tenants",
        "webhook_endpoints",
        type_="foreignkey",
    )
    op.drop_table("tenants")
