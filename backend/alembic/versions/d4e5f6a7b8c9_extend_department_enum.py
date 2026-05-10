"""Расширить CHECK на tickets.department до 7 отделов

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-10 00:00:00.000000

Добавляем 4 новых отдела к таксономии: procurement, security, facilities,
documents. Старые ('IT', 'HR', 'finance') остаются — никаких миграций
данных не требуется.

Подход: DROP старого CHECK + CREATE нового. ALTER CONSTRAINT для CHECK
в Postgres не поддерживается, нужно пересоздавать целиком.

NOT VALID: применяем без сканирования таблицы — все существующие строки
по построению проходят новый, более широкий CHECK (он надмножество старого).
"""

from typing import Sequence, Union

from alembic import op


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_DEPARTMENTS = ("IT", "HR", "finance", "procurement", "security", "facilities", "documents")
_OLD_DEPARTMENTS = ("IT", "HR", "finance")


def _check_clause(values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"CHECK (department IN ({quoted}))"


def upgrade() -> None:
    op.execute("ALTER TABLE tickets DROP CONSTRAINT IF EXISTS ck_tickets_department")
    op.execute(
        "ALTER TABLE tickets ADD CONSTRAINT ck_tickets_department "
        f"{_check_clause(_NEW_DEPARTMENTS)} NOT VALID"
    )


def downgrade() -> None:
    # Откат может упасть, если в БД уже есть тикеты в новых отделах.
    # На прод-данных откатывать не нужно — но если кто-то всё же вызовет
    # downgrade, явно показать, что строки в новых отделах несовместимы.
    op.execute("ALTER TABLE tickets DROP CONSTRAINT IF EXISTS ck_tickets_department")
    op.execute(
        "ALTER TABLE tickets ADD CONSTRAINT ck_tickets_department "
        f"{_check_clause(_OLD_DEPARTMENTS)} NOT VALID"
    )
