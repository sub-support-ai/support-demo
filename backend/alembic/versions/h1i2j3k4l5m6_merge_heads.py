"""merge komar index chain with main head

Revision ID: h1i2j3k4l5m6
Revises: g1h2i3j4k5l7, e7f8a9b0c1d2
Create Date: 2026-05-09 00:00:00.000000

Объединяет:
  g1h2i3j4k5l7 — составной индекс SLA (komar)
  e7f8a9b0c1d2 — ai_stage для псевдо-стриминга (main HEAD)
"""

from collections.abc import Sequence

revision: str = "h1i2j3k4l5m6"
down_revision: str | Sequence[str] | None = ("g1h2i3j4k5l7", "e7f8a9b0c1d2")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
