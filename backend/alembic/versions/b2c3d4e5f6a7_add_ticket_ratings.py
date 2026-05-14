"""add ticket_ratings table (CSAT)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-09

Таблица ticket_ratings хранит оценку 1–5 от пользователя после закрытия тикета.
Уникальное ограничение на ticket_id — один тикет, одна оценка (UPSERT-friendly).
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ticket_ratings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "ticket_id",
            sa.Integer(),
            sa.ForeignKey("tickets.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_ticket_ratings_ticket_id", "ticket_ratings", ["ticket_id"])
    op.create_index("ix_ticket_ratings_user_id", "ticket_ratings", ["user_id"])

    # Ограничение на диапазон оценки (Postgres, SQLite игнорирует CHECK)
    op.create_check_constraint(
        "ck_ticket_ratings_rating_range",
        "ticket_ratings",
        "rating >= 1 AND rating <= 5",
    )


def downgrade() -> None:
    op.drop_table("ticket_ratings")
