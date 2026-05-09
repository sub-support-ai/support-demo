"""add role and department check constraints

Revision ID: f3a4b5c6d7e8
Revises: 2eff2e137a7e
Create Date: 2026-05-09 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "2eff2e137a7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CHECK на уровне БД защищают от прямой записи вне приложения
    # (миграции, seed-скрипты, psql). Pydantic-валидация работает только
    # через HTTP — здесь последний барьер перед хранением невалидных данных.
    #
    # NOT VALID: применяем ограничение без проверки существующих строк
    # (они уже корректны по логике приложения) и без блокировки таблицы
    # на время сканирования. После деплоя можно запустить VALIDATE
    # в отдельной транзакции, если нужна гарантия для старых данных.
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT ck_users_role "
        "CHECK (role IN ('user', 'agent', 'admin')) NOT VALID"
    )
    op.execute(
        "ALTER TABLE tickets ADD CONSTRAINT ck_tickets_department "
        "CHECK (department IN ('IT', 'HR', 'finance')) NOT VALID"
    )


def downgrade() -> None:
    op.drop_constraint("ck_tickets_department", "tickets", type_="check")
    op.drop_constraint("ck_users_role", "users", type_="check")
