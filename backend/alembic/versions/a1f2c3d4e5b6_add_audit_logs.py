"""add audit_logs table

Revision ID: a1f2c3d4e5b6
Revises: e868b18c75f1
Create Date: 2026-04-20 12:00:00.000000

Добавляет таблицу audit_logs для журнала важных событий
(login/register/ticket.create/delete/role.change).

Написана вручную, а не через autogenerate, потому что:
  - autogenerate требует подключения к прод-похожей БД, а это мешает
    оффлайн-разработке;
  - таблица простая, без FK и миграций данных — руками быстрее и
    контролируемее;
  - downgrade тривиален (drop_table), тоже пишем сразу.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1f2c3d4e5b6"
down_revision: str | Sequence[str] | None = "e868b18c75f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        # user_id БЕЗ ForeignKey — см. docstring модели AuditLog:
        # если юзера удалят, аудит его действий всё равно должен остаться.
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("target_type", sa.String(length=30), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("details", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Главные выборки: "все события юзера X" и "все события типа Y".
    # Составной (user_id, created_at) поможет ORDER BY created_at DESC
    # с фильтром по user_id отрабатывать по индексу.
    op.create_index(op.f("ix_audit_logs_id"), "audit_logs", ["id"], unique=False)
    op.create_index(op.f("ix_audit_logs_user_id"), "audit_logs", ["user_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"], unique=False)
    op.create_index(op.f("ix_audit_logs_created_at"), "audit_logs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_logs_created_at"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_action"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_user_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_id"), table_name="audit_logs")
    op.drop_table("audit_logs")
