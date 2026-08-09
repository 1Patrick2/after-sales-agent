"""bind approval tokens to a unique JWT id

Revision ID: 0009_approval_jti
Revises: 0008_customer_profiles
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0009_approval_jti"
down_revision: str | None = "0008_customer_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add a nullable unique token id for existing and future tickets."""

    op.add_column(
        "support_tickets",
        sa.Column("approval_jti", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_support_tickets_approval_jti",
        "support_tickets",
        ["approval_jti"],
        unique=True,
    )


def downgrade() -> None:
    """Remove the approval token id column."""

    op.drop_index("ix_support_tickets_approval_jti", table_name="support_tickets")
    op.drop_column("support_tickets", "approval_jti")
