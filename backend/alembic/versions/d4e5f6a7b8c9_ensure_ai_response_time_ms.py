"""ensure ai response timing column exists

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-29

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = inspect(op.get_bind())
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    if not _has_column("ai_logs", "ai_response_time_ms"):
        op.add_column(
            "ai_logs",
            sa.Column("ai_response_time_ms", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    # Repair migration: do not drop the column on downgrade, because fresh
    # databases already get it from the baseline migration.
    pass
