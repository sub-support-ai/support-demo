"""add_ticket_kind

Adds ticket_kind column to tickets table.

ticket_kind classifies the ITSM category:
  incident         — something is broken
  service_request  — user asks for something (access, equipment, info)
  access_request   — subset of service_request, explicit for routing
  security_incident — potential security breach, top-priority

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-05-15 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "l2m3n4o5p6q7"
down_revision: str | Sequence[str] | None = "k1l2m3n4o5p6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column(
            "ticket_kind",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'incident'"),
        ),
    )
    op.create_index("ix_tickets_ticket_kind", "tickets", ["ticket_kind"])


def downgrade() -> None:
    op.drop_index("ix_tickets_ticket_kind", table_name="tickets")
    op.drop_column("tickets", "ticket_kind")
