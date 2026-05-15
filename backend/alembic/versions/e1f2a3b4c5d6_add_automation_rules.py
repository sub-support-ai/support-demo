"""add_automation_rules

Merges upstream heads f7a8b9c0d1e2 (add_intake_state_to_conversations)
and j1k2l3m4n5o6 (add_intake_state_to_conversations), then creates the
automation_rules table.

Revision ID: e1f2a3b4c5d6
Revises: f7a8b9c0d1e2, j1k2l3m4n5o6
Create Date: 2026-05-15 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = ("f7a8b9c0d1e2", "j1k2l3m4n5o6")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "automation_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("trigger", sa.String(50), nullable=False),
        sa.Column(
            "conditions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="'[]'",
        ),
        sa.Column(
            "actions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="'[]'",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("name", name="uq_automation_rules_name"),
    )
    op.create_index("ix_automation_rules_id", "automation_rules", ["id"])
    op.create_index("ix_automation_rules_trigger", "automation_rules", ["trigger"])

    # Предустановленные правила для демо
    op.execute(
        sa.text(
            """
            INSERT INTO automation_rules
                (name, description, is_active, priority, trigger, conditions, actions)
            VALUES
            (
                'Фишинг → SOC flow',
                'При подтверждении тикета с типом Фишинг: критический приоритет, SLA 15 мин, комментарий.',
                true, 10, 'ticket_confirmed',
                '[{"field": "department", "op": "eq", "value": "security"},
                  {"field": "request_type", "op": "contains", "value": "Фишинг"}]',
                '[{"type": "set_ai_priority", "value": "критический"},
                  {"type": "override_sla_minutes", "value": 15},
                  {"type": "add_comment", "value": "Автоматика: фишинговая атака → SOC flow активирован, SLA 15 мин."}]'
            ),
            (
                'VPN → IT Network',
                'Тикеты с типом VPN направляются в IT с комментарием.',
                true, 20, 'ticket_confirmed',
                '[{"field": "request_type", "op": "contains", "value": "VPN"}]',
                '[{"type": "reassign_department", "value": "IT"},
                  {"type": "add_comment", "value": "Автоматика: VPN-запрос → назначен отдел ИТ (сетевая команда)."}]'
            ),
            (
                'Reopened 2+ раза → эскалация',
                'Тикет переоткрыт 2 и более раз → немедленная эскалация к старшему агенту.',
                true, 30, 'ticket_reopened',
                '[{"field": "reopen_count", "op": "gte", "value": 2}]',
                '[{"type": "escalate_to_senior"},
                  {"type": "add_comment", "value": "Автоматика: тикет переоткрыт 2+ раза → эскалация к старшему специалисту."}]'
            ),
            (
                'Нет ответа 24ч → напоминание',
                'Тикет подтверждён, агент не ответил 24 часа → системное напоминание.',
                true, 50, 'ticket_no_reply',
                '[]',
                '[{"type": "add_comment", "value": "Автоматика: 24 часа без ответа агента. Пожалуйста, обработайте обращение."}]'
            )
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_automation_rules_trigger", table_name="automation_rules")
    op.drop_index("ix_automation_rules_id", table_name="automation_rules")
    op.drop_table("automation_rules")
