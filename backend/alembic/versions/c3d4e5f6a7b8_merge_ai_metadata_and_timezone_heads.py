"""merge ai metadata and timezone heads

Revision ID: c3d4e5f6a7b8
Revises: b2c4e6f8a0d2, b7c9e8f1a2d3
Create Date: 2026-04-29

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = (
    "b2c4e6f8a0d2",
    "b7c9e8f1a2d3",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
