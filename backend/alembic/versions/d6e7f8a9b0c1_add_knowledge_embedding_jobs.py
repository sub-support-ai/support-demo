"""add knowledge embedding jobs

Revision ID: d6e7f8a9b0c1
Revises: d5e6f7a8b9c0
Create Date: 2026-05-07 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d6e7f8a9b0c1"
down_revision: str | Sequence[str] | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_embedding_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=True),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column(
            "run_after", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("updated_chunks", sa.Integer(), nullable=False),
        sa.Column("embedding_model", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["article_id"], ["knowledge_articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_knowledge_embedding_jobs_id"), "knowledge_embedding_jobs", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_knowledge_embedding_jobs_article_id"),
        "knowledge_embedding_jobs",
        ["article_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_embedding_jobs_requested_by_user_id"),
        "knowledge_embedding_jobs",
        ["requested_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_embedding_jobs_status"),
        "knowledge_embedding_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_embedding_jobs_run_after"),
        "knowledge_embedding_jobs",
        ["run_after"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_embedding_jobs_status_run_after_id",
        "knowledge_embedding_jobs",
        ["status", "run_after", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_embedding_jobs_status_run_after_id", table_name="knowledge_embedding_jobs"
    )
    op.drop_index(
        op.f("ix_knowledge_embedding_jobs_run_after"), table_name="knowledge_embedding_jobs"
    )
    op.drop_index(op.f("ix_knowledge_embedding_jobs_status"), table_name="knowledge_embedding_jobs")
    op.drop_index(
        op.f("ix_knowledge_embedding_jobs_requested_by_user_id"),
        table_name="knowledge_embedding_jobs",
    )
    op.drop_index(
        op.f("ix_knowledge_embedding_jobs_article_id"), table_name="knowledge_embedding_jobs"
    )
    op.drop_index(op.f("ix_knowledge_embedding_jobs_id"), table_name="knowledge_embedding_jobs")
    op.drop_table("knowledge_embedding_jobs")
