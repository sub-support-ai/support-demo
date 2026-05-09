"""add first_response_at to tickets for TTFR metric

Revision ID: a1b2c3d4e5f6
Revises: f3a4b5c6d7e8
Create Date: 2026-05-09 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Время первого ответа агента — для метрики TTFR (Time To First Response).
    # NOT VALID: применяем без блокировки всей таблицы; для существующих тикетов
    # значение NULL (данных до этой миграции нет), это ожидаемо.
    op.add_column(
        "tickets",
        sa.Column(
            "first_response_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Время первого ответа агента (для метрики TTFR)",
        ),
    )
    # Индекс не нужен: поле используется только в агрегатных AVG-запросах,
    # которые делают seq-scan по всей таблице всё равно.


def downgrade() -> None:
    op.drop_column("tickets", "first_response_at")
