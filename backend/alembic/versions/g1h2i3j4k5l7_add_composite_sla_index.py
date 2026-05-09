"""add composite index for sla escalation

Revision ID: g1h2i3j4k5l7
Revises: g1h2i3j4k5l6
Create Date: 2026-05-09 00:00:00.000000
"""

from typing import Sequence, Union
from alembic import op

revision: str = "g1h2i3j4k5l7"
down_revision: Union[str, None] = "g1h2i3j4k5l6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_tickets_status_sla_deadline",
        "tickets",
        ["status", "sla_deadline_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_tickets_status_sla_deadline", table_name="tickets")

    #пункт 1, норм название исправил