"""add sla feedback and comments

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("request_type", sa.String(length=50), nullable=True))
    op.add_column("tickets", sa.Column("request_details", sa.Text(), nullable=True))
    op.add_column("tickets", sa.Column("sla_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "tickets", sa.Column("sla_deadline_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "tickets", sa.Column("reopen_count", sa.Integer(), server_default="0", nullable=False)
    )
    op.create_index(
        op.f("ix_tickets_sla_deadline_at"), "tickets", ["sla_deadline_at"], unique=False
    )

    op.create_table(
        "ticket_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("author_username", sa.String(length=100), nullable=False),
        sa.Column("author_role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("internal", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ticket_comments_id"), "ticket_comments", ["id"], unique=False)
    op.create_index(
        op.f("ix_ticket_comments_ticket_id"), "ticket_comments", ["ticket_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ticket_comments_ticket_id"), table_name="ticket_comments")
    op.drop_index(op.f("ix_ticket_comments_id"), table_name="ticket_comments")
    op.drop_table("ticket_comments")

    op.drop_index(op.f("ix_tickets_sla_deadline_at"), table_name="tickets")
    op.drop_column("tickets", "reopen_count")
    op.drop_column("tickets", "sla_deadline_at")
    op.drop_column("tickets", "sla_started_at")
    op.drop_column("tickets", "request_details")
    op.drop_column("tickets", "request_type")
