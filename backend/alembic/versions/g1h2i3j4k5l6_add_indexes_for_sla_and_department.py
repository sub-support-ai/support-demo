"""add index for department

Revision ID: g1h2i3j4k5l6
Revises: f3a4b5c6d7e8
Create Date: 2026-05-09 00:00:00.000000
"""

from typing import Sequence, Union
from alembic import op

revision: str = "g1h2i3j4k5l6"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_tickets_department", "tickets", ["department"])


def downgrade() -> None:
    op.drop_index("ix_tickets_department", table_name="tickets")

    #пункт 2

    