"""add intake_state to conversations

Revision ID: j1k2l3m4n5o6
Revises: i1j2k3l4m5n6
Create Date: 2026-05-14 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "j1k2l3m4n5o6"
down_revision: str | Sequence[str] | None = "i1j2k3l4m5n6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("intake_state", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "intake_state")
