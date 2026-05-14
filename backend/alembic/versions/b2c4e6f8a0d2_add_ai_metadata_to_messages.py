"""add ai metadata to messages (sources, confidence, escalate)

Revision ID: b2c4e6f8a0d2
Revises: a1f2c3d4e5b6
Create Date: 2026-04-25 12:00:00.000000

Добавляет на таблицу messages четыре nullable-поля для AI-сообщений:
  - ai_confidence       — уверенность модели в ответе (0.0–1.0)
  - ai_escalate         — модель сама попросила эскалацию
  - sources             — список источников (RAG), JSON
  - requires_escalation — флаг "красной зоны" (confidence < 0.6 или escalate)

Все поля nullable, чтобы:
  - не ломать существующие user-сообщения (у них этих полей нет в принципе);
  - не требовать backfill для старых AI-сообщений до перехода на новый
    контракт /ai/answer (для них значения остаются NULL, и UI просто не
    показывает источники / не предлагает эскалацию).

Написана вручную — таблица простая, autogenerate здесь не нужен.
Downgrade — drop_column для всех четырёх колонок.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c4e6f8a0d2"
down_revision: str | Sequence[str] | None = "a1f2c3d4e5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.add_column(sa.Column("ai_confidence", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("ai_escalate", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("sources", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("requires_escalation", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_column("requires_escalation")
        batch_op.drop_column("sources")
        batch_op.drop_column("ai_escalate")
        batch_op.drop_column("ai_confidence")
