"""add knowledge articles

Revision ID: d1e2f3a4b5c6
Revises: d0e1f2a3b4c5
Create Date: 2026-05-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_articles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("department", sa.String(length=20), nullable=True),
        sa.Column("request_type", sa.String(length=50), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("keywords", sa.Text(), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_articles_id"), "knowledge_articles", ["id"], unique=False)
    op.create_index(
        op.f("ix_knowledge_articles_department"), "knowledge_articles", ["department"], unique=False
    )
    op.create_index(
        op.f("ix_knowledge_articles_request_type"),
        "knowledge_articles",
        ["request_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_articles_title"), "knowledge_articles", ["title"], unique=False
    )
    op.create_index(
        op.f("ix_knowledge_articles_is_active"), "knowledge_articles", ["is_active"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_knowledge_articles_is_active"), table_name="knowledge_articles")
    op.drop_index(op.f("ix_knowledge_articles_title"), table_name="knowledge_articles")
    op.drop_index(op.f("ix_knowledge_articles_request_type"), table_name="knowledge_articles")
    op.drop_index(op.f("ix_knowledge_articles_department"), table_name="knowledge_articles")
    op.drop_index(op.f("ix_knowledge_articles_id"), table_name="knowledge_articles")
    op.drop_table("knowledge_articles")
