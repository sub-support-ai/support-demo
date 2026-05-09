"""ticket_comments.author_id SET NULL + composite index (agent_id, status)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-10 00:00:00.000000

Changes:
  1. ticket_comments.author_id — nullable=True, ondelete SET NULL.
     Позволяет удалять пользователей, не теряя историю комментариев
     (author_username / author_role сохраняются как «снимок» на момент
     создания).

  2. Индекс (agent_id, status) на tickets — ускоряет запросы агента к
     «своим» открытым тикетам, а также SLA-воркер (WHERE agent_id=X AND
     status IN (...)). Без индекса каждый тик воркера делает seq-scan.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. author_id: nullable + SET NULL ─────────────────────────────────────

    # Снимаем старый FK-constraint (имя генерирует SQLAlchemy по умолчанию)
    with op.batch_alter_table("ticket_comments", schema=None) as batch_op:
        batch_op.alter_column(
            "author_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
        # Пересоздаём FK с ondelete="SET NULL"
        # Сначала убираем старый, затем добавляем новый.
        # batch_alter_table сам управляет именем constraint'а на SQLite.
        batch_op.drop_constraint("ticket_comments_author_id_fkey", type_="foreignkey")
        batch_op.create_foreign_key(
            "ticket_comments_author_id_fkey",
            "users",
            ["author_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # ── 2. Составной индекс (agent_id, status) ────────────────────────────────
    op.create_index(
        "ix_tickets_agent_id_status",
        "tickets",
        ["agent_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    # Удаляем индекс
    op.drop_index("ix_tickets_agent_id_status", table_name="tickets")

    # Восстанавливаем author_id как NOT NULL без SET NULL
    with op.batch_alter_table("ticket_comments", schema=None) as batch_op:
        batch_op.drop_constraint("ticket_comments_author_id_fkey", type_="foreignkey")
        batch_op.create_foreign_key(
            "ticket_comments_author_id_fkey",
            "users",
            ["author_id"],
            ["id"],
        )
        batch_op.alter_column(
            "author_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
