"""add response templates

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-05-06 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "response_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("department", sa.String(length=20), nullable=True),
        sa.Column("request_type", sa.String(length=50), nullable=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_response_templates_id"), "response_templates", ["id"], unique=False)
    op.create_index(op.f("ix_response_templates_department"), "response_templates", ["department"], unique=False)
    op.create_index(op.f("ix_response_templates_request_type"), "response_templates", ["request_type"], unique=False)
    op.create_index(op.f("ix_response_templates_is_active"), "response_templates", ["is_active"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_response_templates_is_active"), table_name="response_templates")
    op.drop_index(op.f("ix_response_templates_request_type"), table_name="response_templates")
    op.drop_index(op.f("ix_response_templates_department"), table_name="response_templates")
    op.drop_index(op.f("ix_response_templates_id"), table_name="response_templates")
    op.drop_table("response_templates")
