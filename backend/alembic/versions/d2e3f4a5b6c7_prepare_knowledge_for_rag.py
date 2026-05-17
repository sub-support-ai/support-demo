"""prepare knowledge articles for rag

Revision ID: d2e3f4a5b6c7
Revises: d1e2f3a4b5c6
Create Date: 2026-05-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: str | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("knowledge_articles", sa.Column("problem", sa.Text(), nullable=True))
    op.add_column("knowledge_articles", sa.Column("symptoms", sa.JSON(), nullable=True))
    op.add_column("knowledge_articles", sa.Column("applies_to", sa.JSON(), nullable=True))
    op.add_column("knowledge_articles", sa.Column("steps", sa.JSON(), nullable=True))
    op.add_column("knowledge_articles", sa.Column("when_to_escalate", sa.Text(), nullable=True))
    op.add_column("knowledge_articles", sa.Column("required_context", sa.JSON(), nullable=True))
    op.add_column("knowledge_articles", sa.Column("owner", sa.String(length=120), nullable=True))
    op.add_column(
        "knowledge_articles",
        sa.Column(
            "access_scope", sa.String(length=20), nullable=False, server_default=sa.text("'public'")
        ),
    )
    op.add_column(
        "knowledge_articles",
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "knowledge_articles", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "knowledge_articles", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("knowledge_articles", sa.Column("search_text", sa.Text(), nullable=True))
    op.add_column(
        "knowledge_articles", sa.Column("embedding_model", sa.String(length=80), nullable=True)
    )
    op.add_column(
        "knowledge_articles",
        sa.Column("embedding_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "knowledge_articles",
        sa.Column("view_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "knowledge_articles",
        sa.Column("helped_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "knowledge_articles",
        sa.Column("not_helped_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "knowledge_articles",
        sa.Column("not_relevant_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index(
        op.f("ix_knowledge_articles_access_scope"),
        "knowledge_articles",
        ["access_scope"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_articles_expires_at"), "knowledge_articles", ["expires_at"], unique=False
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("embedding_model", sa.String(length=80), nullable=True),
        sa.Column("embedding_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["article_id"], ["knowledge_articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_chunks_id"), "knowledge_chunks", ["id"], unique=False)
    op.create_index(
        op.f("ix_knowledge_chunks_article_id"), "knowledge_chunks", ["article_id"], unique=False
    )
    op.create_index(
        op.f("ix_knowledge_chunks_is_active"), "knowledge_chunks", ["is_active"], unique=False
    )

    op.create_table(
        "knowledge_article_feedbacks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("escalated_ticket_id", sa.Integer(), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("feedback", sa.String(length=20), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["article_id"], ["knowledge_articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["escalated_ticket_id"], ["tickets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_knowledge_article_feedbacks_id"),
        "knowledge_article_feedbacks",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_article_feedbacks_article_id"),
        "knowledge_article_feedbacks",
        ["article_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_article_feedbacks_conversation_id"),
        "knowledge_article_feedbacks",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_article_feedbacks_message_id"),
        "knowledge_article_feedbacks",
        ["message_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_article_feedbacks_user_id"),
        "knowledge_article_feedbacks",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_article_feedbacks_escalated_ticket_id"),
        "knowledge_article_feedbacks",
        ["escalated_ticket_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_article_feedbacks_feedback"),
        "knowledge_article_feedbacks",
        ["feedback"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_knowledge_article_feedbacks_feedback"), table_name="knowledge_article_feedbacks"
    )
    op.drop_index(
        op.f("ix_knowledge_article_feedbacks_escalated_ticket_id"),
        table_name="knowledge_article_feedbacks",
    )
    op.drop_index(
        op.f("ix_knowledge_article_feedbacks_user_id"), table_name="knowledge_article_feedbacks"
    )
    op.drop_index(
        op.f("ix_knowledge_article_feedbacks_message_id"), table_name="knowledge_article_feedbacks"
    )
    op.drop_index(
        op.f("ix_knowledge_article_feedbacks_conversation_id"),
        table_name="knowledge_article_feedbacks",
    )
    op.drop_index(
        op.f("ix_knowledge_article_feedbacks_article_id"), table_name="knowledge_article_feedbacks"
    )
    op.drop_index(
        op.f("ix_knowledge_article_feedbacks_id"), table_name="knowledge_article_feedbacks"
    )
    op.drop_table("knowledge_article_feedbacks")

    op.drop_index(op.f("ix_knowledge_chunks_is_active"), table_name="knowledge_chunks")
    op.drop_index(op.f("ix_knowledge_chunks_article_id"), table_name="knowledge_chunks")
    op.drop_index(op.f("ix_knowledge_chunks_id"), table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")

    op.drop_index(op.f("ix_knowledge_articles_expires_at"), table_name="knowledge_articles")
    op.drop_index(op.f("ix_knowledge_articles_access_scope"), table_name="knowledge_articles")
    op.drop_column("knowledge_articles", "not_relevant_count")
    op.drop_column("knowledge_articles", "not_helped_count")
    op.drop_column("knowledge_articles", "helped_count")
    op.drop_column("knowledge_articles", "view_count")
    op.drop_column("knowledge_articles", "embedding_updated_at")
    op.drop_column("knowledge_articles", "embedding_model")
    op.drop_column("knowledge_articles", "search_text")
    op.drop_column("knowledge_articles", "expires_at")
    op.drop_column("knowledge_articles", "reviewed_at")
    op.drop_column("knowledge_articles", "version")
    op.drop_column("knowledge_articles", "access_scope")
    op.drop_column("knowledge_articles", "owner")
    op.drop_column("knowledge_articles", "required_context")
    op.drop_column("knowledge_articles", "when_to_escalate")
    op.drop_column("knowledge_articles", "steps")
    op.drop_column("knowledge_articles", "applies_to")
    op.drop_column("knowledge_articles", "symptoms")
    op.drop_column("knowledge_articles", "problem")
