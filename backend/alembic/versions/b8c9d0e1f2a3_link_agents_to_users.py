"""link agents to users

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-05-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_agents_user_id"), "agents", ["user_id"], unique=True)
    op.create_foreign_key(
        "fk_agents_user_id_users",
        "agents",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        """
        UPDATE agents
        SET user_id = (
            SELECT users.id
            FROM users
            WHERE users.email = agents.email OR users.username = agents.username
            LIMIT 1
        )
        WHERE user_id IS NULL
          AND EXISTS (
              SELECT 1
              FROM users
              WHERE users.email = agents.email OR users.username = agents.username
          )
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_agents_user_id_users", "agents", type_="foreignkey")
    op.drop_index(op.f("ix_agents_user_id"), table_name="agents")
    op.drop_column("agents", "user_id")
