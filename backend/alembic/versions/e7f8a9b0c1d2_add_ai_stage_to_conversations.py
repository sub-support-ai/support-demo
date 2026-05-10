"""Добавить ai_stage к conversations (псевдо-стриминг)

Revision ID: e7f8a9b0c1d2
Revises: d5e8f9a0b1c2
Create Date: 2026-05-10 00:00:00.000000

ai_stage хранит текущую стадию обработки AI-запроса:
  thinking  — разбираем вопрос
  searching — ищем в базе знаний
  found_kb  — KB-статья найдена
  generating — генерируем LLM-ответ
  NULL      — нет активной обработки (idle / завершено)

Поле nullable VARCHAR(20); значения короткие, индекс не нужен
(запрашивается только по conversation.id).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "d5e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("ai_stage", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "ai_stage")
