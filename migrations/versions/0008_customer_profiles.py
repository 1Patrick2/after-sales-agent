"""add tenant-scoped customer profiles for business policy decisions

Revision ID: 0008_customer_profiles
Revises: 0007_runtime_schema_alignment
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0008_customer_profiles"
down_revision: str | None = "0007_runtime_schema_alignment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the profile read model used by the after-sales capability."""

    op.create_table(
        "customer_profiles",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("vip_level", sa.String(length=32), nullable=False, server_default="standard"),
        sa.Column("risk_flags", sa.JSON(), nullable=False, server_default=sa.text("('[]')")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_customer_profile_owner"),
    )
    op.create_index("ix_customer_profiles_tenant_id", "customer_profiles", ["tenant_id"])
    op.create_index("ix_customer_profiles_user_id", "customer_profiles", ["user_id"])


def downgrade() -> None:
    """Remove the profile read model."""

    op.drop_index("ix_customer_profiles_user_id", table_name="customer_profiles")
    op.drop_index("ix_customer_profiles_tenant_id", table_name="customer_profiles")
    op.drop_table("customer_profiles")
