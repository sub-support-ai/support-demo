"""add knowledge full text search

Revision ID: d3e4f5a6b7c8
Revises: d2e3f4a5b6c7
Create Date: 2026-05-06 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEARCH_VECTOR_EXPRESSION = """
setweight(
    to_tsvector(
        'russian'::regconfig,
        coalesce(title, '') || ' ' ||
        coalesce(keywords, '') || ' ' ||
        coalesce(request_type, '')
    ),
    'A'
) ||
setweight(
    to_tsvector(
        'simple'::regconfig,
        coalesce(title, '') || ' ' ||
        coalesce(keywords, '') || ' ' ||
        coalesce(request_type, '')
    ),
    'A'
) ||
setweight(
    to_tsvector(
        'russian'::regconfig,
        coalesce(problem, '')
    ),
    'B'
) ||
setweight(
    to_tsvector(
        'russian'::regconfig,
        coalesce(body, '') || ' ' ||
        coalesce(when_to_escalate, '')
    ),
    'C'
) ||
setweight(
    to_tsvector(
        'simple'::regconfig,
        coalesce(search_text, '')
    ),
    'D'
)
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        UPDATE knowledge_articles
        SET search_text = concat_ws(
            E'\n',
            title,
            body,
            problem,
            when_to_escalate,
            keywords,
            request_type,
            department
        )
        WHERE search_text IS NULL OR btrim(search_text) = ''
        """
    )
    op.execute(
        f"""
        ALTER TABLE knowledge_articles
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS ({SEARCH_VECTOR_EXPRESSION}) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_knowledge_articles_search_vector
        ON knowledge_articles
        USING GIN (search_vector)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_knowledge_articles_search_filters
        ON knowledge_articles (is_active, access_scope, department, request_type)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_knowledge_articles_search_filters")
    op.execute("DROP INDEX IF EXISTS ix_knowledge_articles_search_vector")
    op.execute("ALTER TABLE knowledge_articles DROP COLUMN IF EXISTS search_vector")
