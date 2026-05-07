"""add pgvector knowledge embeddings

Revision ID: d5e6f7a8b9c0
Revises: d3e4f5a6b7c8, f6a7b8c9d0e1
Create Date: 2026-05-07 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = ("d3e4f5a6b7c8", "f6a7b8c9d0e1")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_available_extensions
                WHERE name = 'vector'
            ) THEN
                CREATE EXTENSION IF NOT EXISTS vector;

                ALTER TABLE knowledge_articles
                    ADD COLUMN IF NOT EXISTS embedding vector(768);

                ALTER TABLE knowledge_chunks
                    ADD COLUMN IF NOT EXISTS embedding vector(768);

                CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding_hnsw
                    ON knowledge_chunks
                    USING hnsw (embedding vector_cosine_ops)
                    WHERE embedding IS NOT NULL AND is_active IS TRUE;

                CREATE INDEX IF NOT EXISTS ix_knowledge_articles_embedding_hnsw
                    ON knowledge_articles
                    USING hnsw (embedding vector_cosine_ops)
                    WHERE embedding IS NOT NULL AND is_active IS TRUE;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_knowledge_articles_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_embedding_hnsw")
    op.execute("ALTER TABLE knowledge_articles DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS embedding")
