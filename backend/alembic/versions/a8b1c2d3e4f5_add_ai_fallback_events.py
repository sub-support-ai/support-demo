"""add ai fallback events

Revision ID: a8b1c2d3e4f5
Revises: d6e7f8a9b0c1
Create Date: 2026-05-08 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8b1c2d3e4f5"
down_revision: Union[str, None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_fallback_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("ticket_id", sa.Integer(), nullable=True),
        sa.Column("service", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_fallback_events_id"), "ai_fallback_events", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_ai_fallback_events_conversation_id"),
        "ai_fallback_events",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_fallback_events_ticket_id"),
        "ai_fallback_events",
        ["ticket_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_fallback_events_service"),
        "ai_fallback_events",
        ["service"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_fallback_events_reason"),
        "ai_fallback_events",
        ["reason"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_fallback_events_created_at"),
        "ai_fallback_events",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_fallback_events_created_at"), table_name="ai_fallback_events")
    op.drop_index(op.f("ix_ai_fallback_events_reason"), table_name="ai_fallback_events")
    op.drop_index(op.f("ix_ai_fallback_events_service"), table_name="ai_fallback_events")
    op.drop_index(op.f("ix_ai_fallback_events_ticket_id"), table_name="ai_fallback_events")
    op.drop_index(
        op.f("ix_ai_fallback_events_conversation_id"), table_name="ai_fallback_events"
    )
    op.drop_index(op.f("ix_ai_fallback_events_id"), table_name="ai_fallback_events")
    op.drop_table("ai_fallback_events")
