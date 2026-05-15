"""add_assets

Adds the `assets` table (CMDB-lite) and a nullable `asset_id` FK column
to the `tickets` table.

Notes:
  - serial_number uniqueness is enforced by a partial index
    (WHERE serial_number IS NOT NULL) so that multiple assets without a
    serial number can coexist.
  - asset_id on tickets is SET NULL on delete — deleting an asset does NOT
    cascade-delete its tickets; the router blocks deletion when tickets exist.
  - affected_item on tickets is KEPT as a free-text fallback.

Revision ID: k1l2m3n4o5p6
Revises: e1f2a3b4c5d6
Create Date: 2026-05-15 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "k1l2m3n4o5p6"
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── 1. Создаём таблицу assets ────────────────────────────────────────────
    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("asset_type", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("serial_number", sa.String(100), nullable=True),
        sa.Column(
            "owner_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("office", sa.String(100), nullable=True),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
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
    )

    op.create_index("ix_assets_id", "assets", ["id"])
    op.create_index("ix_assets_asset_type", "assets", ["asset_type"])
    op.create_index("ix_assets_status", "assets", ["status"])
    op.create_index("ix_assets_owner_user_id", "assets", ["owner_user_id"])

    # Уникальность serial_number только среди непустых значений
    op.create_index(
        "uq_assets_serial_notnull",
        "assets",
        ["serial_number"],
        unique=True,
        postgresql_where=sa.text("serial_number IS NOT NULL"),
    )

    # ── 2. Добавляем asset_id в tickets ──────────────────────────────────────
    op.add_column(
        "tickets",
        sa.Column(
            "asset_id",
            sa.Integer(),
            sa.ForeignKey("assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_tickets_asset_id", "tickets", ["asset_id"])


def downgrade() -> None:
    op.drop_index("ix_tickets_asset_id", table_name="tickets")
    op.drop_column("tickets", "asset_id")

    op.drop_index("uq_assets_serial_notnull", table_name="assets")
    op.drop_index("ix_assets_owner_user_id", table_name="assets")
    op.drop_index("ix_assets_status", table_name="assets")
    op.drop_index("ix_assets_asset_type", table_name="assets")
    op.drop_index("ix_assets_id", table_name="assets")
    op.drop_table("assets")
