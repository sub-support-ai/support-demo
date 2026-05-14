"""add_reopen_count_to_tickets

Revision ID: 2eff2e137a7e
Revises: a8b1c2d3e4f5
Create Date: 2026-05-08 22:51:40.078456
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2eff2e137a7e"
down_revision: str | Sequence[str] | None = "a8b1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    if not _has_column("tickets", "reopen_count"):
        op.add_column(
            "tickets",
            sa.Column(
                "reopen_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )
        op.alter_column("tickets", "reopen_count", server_default=None)


def downgrade() -> None:
    if _has_column("tickets", "reopen_count"):
        op.drop_column("tickets", "reopen_count")
