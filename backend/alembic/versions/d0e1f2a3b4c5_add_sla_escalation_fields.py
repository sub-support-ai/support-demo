"""add sla escalation fields

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-05-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: str | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tickets", sa.Column("sla_escalated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "tickets",
        sa.Column("sla_escalation_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index(
        op.f("ix_tickets_sla_escalated_at"), "tickets", ["sla_escalated_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_tickets_sla_escalated_at"), table_name="tickets")
    op.drop_column("tickets", "sla_escalation_count")
    op.drop_column("tickets", "sla_escalated_at")
