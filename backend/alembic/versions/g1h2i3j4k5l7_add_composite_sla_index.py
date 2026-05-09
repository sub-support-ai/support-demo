"""add composite index for sla escalation

Revision ID: g1h2i3j4k5l6
Revises: f3a4b5c6d7e8
Create Date: 2026-05-09 00:00:00.000000
"""

from typing import Sequence, Union
from alembic import op

# Alembic не оборачивает в транзакцию — нужно для CREATE INDEX CONCURRENTLY
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    op.get_bind().execution_options(isolation_level="AUTOCOMMIT")
    op.execute(...)

revision: str = "g1h2i3j4k5l6"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Составной индекс для запроса escalate_overdue_tickets:
    #   WHERE status IN ('confirmed', 'in_progress')
    #     AND sla_deadline_at < now
    #     AND sla_escalated_at IS NULL
    #
    # Postgres идёт по индексу (status, sla_deadline_at), быстро отсекает
    # строки по статусу, потом по дедлайну. sla_escalated_at IS NULL
    # проверяется уже на отфильтрованных строках — их мало.
    #
    # CONCURRENTLY — не блокирует таблицу во время построения индекса.
    # Нельзя внутри транзакции, поэтому execute_if не нужен, но нужен
    # autocommit через raw connection.
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tickets_status_sla_deadline "
        "ON tickets (status, sla_deadline_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_tickets_status_sla_deadline")

    #пункт 1, норм название исправил