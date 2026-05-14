"""add intake state fields to conversations

Revision ID: f7a8b9c0d1e2
Revises: 2eff2e137a7e
Create Date: 2026-05-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "2eff2e137a7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    return any(
        c["name"] == column
        for c in inspect(op.get_bind()).get_columns(table)
    )


def upgrade() -> None:
    if not _has_column("conversations", "catalog_code"):
        op.add_column(
            "conversations",
            sa.Column("catalog_code", sa.String(50), nullable=True),
        )
    if not _has_column("conversations", "intake_fields"):
        op.add_column(
            "conversations",
            sa.Column("intake_fields", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("conversations", "intake_fields")
    op.drop_column("conversations", "catalog_code")
