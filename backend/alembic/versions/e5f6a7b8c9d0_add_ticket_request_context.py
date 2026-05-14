"""add ticket request context

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = inspect(op.get_bind())
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    columns = (
        ("requester_name", sa.String(length=100)),
        ("requester_email", sa.String(length=255)),
        ("office", sa.String(length=100)),
        ("affected_item", sa.String(length=150)),
    )
    for name, column_type in columns:
        if not _has_column("tickets", name):
            op.add_column("tickets", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for name in ("affected_item", "office", "requester_email", "requester_name"):
        if _has_column("tickets", name):
            op.drop_column("tickets", name)
