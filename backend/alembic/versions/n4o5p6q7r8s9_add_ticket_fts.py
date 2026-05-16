"""add ticket full-text search (tsvector + GIN index)

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-05-16 00:00:00.000000

PostgreSQL only.
SQLite: no-op — the router falls back to ILIKE for SQLite.

The generated column combines:
  A — title (most specific match; agents search by title first)
  B — body, request_type, ai_category, affected_item
  C — requester_name, office, request_details, requester_email

Both 'russian' and 'simple' configs are combined so that proper nouns
(e.g. "VPN", "Outlook") are found even without morphological analysis.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "n4o5p6q7r8s9"
down_revision: str | None = "m3n4o5p6q7r8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SEARCH_VECTOR_EXPRESSION = """
setweight(to_tsvector('russian'::regconfig, coalesce(title, '')), 'A') ||
setweight(to_tsvector('simple'::regconfig,  coalesce(title, '')), 'A') ||
setweight(
    to_tsvector(
        'russian'::regconfig,
        coalesce(body, '')            || ' ' ||
        coalesce(request_type, '')    || ' ' ||
        coalesce(ai_category, '')     || ' ' ||
        coalesce(affected_item, '')
    ),
    'B'
) ||
setweight(
    to_tsvector(
        'russian'::regconfig,
        coalesce(requester_name, '')  || ' ' ||
        coalesce(office, '')          || ' ' ||
        coalesce(request_details, '') || ' ' ||
        coalesce(requester_email, '')
    ),
    'C'
)
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        f"""
        ALTER TABLE tickets
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS ({SEARCH_VECTOR_EXPRESSION}) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tickets_search_vector
        ON tickets
        USING GIN (search_vector)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_tickets_search_vector")
    op.execute("ALTER TABLE tickets DROP COLUMN IF EXISTS search_vector")
