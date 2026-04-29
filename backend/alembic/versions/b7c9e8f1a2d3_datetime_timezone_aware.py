"""сделать все datetime-колонки timezone-aware

Revision ID: b7c9e8f1a2d3
Revises: a1f2c3d4e5b6
Create Date: 2026-04-21 18:10:00.000000

Фикс скрытого бага, который CI обнаружил при поднятии матрицы Python 3.12/3.13:
    asyncpg.exceptions.DataError: invalid input for query argument $15:
    (can't subtract offset-naive and offset-aware datetimes)

Причина: код везде использует datetime.now(timezone.utc) (aware),
а колонки были объявлены как sa.DateTime() → в Postgres это
TIMESTAMP WITHOUT TIME ZONE, который принимает только naive.
На SQLite типизация слабая, тесты проходили; на Postgres в CI падает.

Правильная жизнь в 2026: хранить время как TIMESTAMP WITH TIME ZONE,
Postgres сам нормализует к UTC. Код с timezone.utc остаётся как есть.

Конвертация данных:
    Старые значения в колонках "голые" без tz. В Postgres при смене типа
    на timestamptz без USING-клаузы он трактует их как local time
    сервера. У нас в CI сервер UTC и мы и так пишем UTC — но в проде
    клиента сервер может быть в любой зоне. Явно конвертируем:
        USING "col" AT TIME ZONE 'UTC'

Миграция написана вручную (а не autogenerate), потому что автогенерация
для 16 одинаковых ALTER COLUMN на 8 таблицах = много шума в diff'е,
и логика USING 'UTC' всё равно требует ручной правки.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'b7c9e8f1a2d3'
down_revision: Union[str, Sequence[str], None] = 'a1f2c3d4e5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Все (таблица, колонка) с datetime-полями в текущих моделях.
# Держим список в одном месте — если добавится новая колонка, дописать
# строку здесь и downgrade разворачивается автоматически.
_DATETIME_COLUMNS = [
    ("users", "created_at"),
    ("users", "updated_at"),
    ("agents", "created_at"),
    ("agents", "updated_at"),
    ("tickets", "ai_processed_at"),
    ("tickets", "created_at"),
    ("tickets", "updated_at"),
    ("tickets", "resolved_at"),
    ("responses", "created_at"),
    ("responses", "updated_at"),
    ("conversations", "created_at"),
    ("conversations", "updated_at"),
    ("messages", "created_at"),
    ("ai_logs", "created_at"),
    ("ai_logs", "reviewed_at"),
    ("audit_logs", "created_at"),
]


def upgrade() -> None:
    # Только Postgres: в SQLite DateTime == TEXT, тип не меняется,
    # batch_alter_table дал бы лишнюю пересборку таблицы впустую.
    # Миграции применяются только к Postgres (см. CI и prod), так что
    # используем op.execute с явным SQL — короче и читабельнее op.alter_column.
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table, column in _DATETIME_COLUMNS:
        op.execute(
            f'ALTER TABLE {table} '
            f'ALTER COLUMN "{column}" TYPE TIMESTAMP WITH TIME ZONE '
            f'USING "{column}" AT TIME ZONE \'UTC\''
        )


def downgrade() -> None:
    # Обратная конвертация: отрезаем tz, оставляем время как оно было в UTC.
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table, column in _DATETIME_COLUMNS:
        op.execute(
            f'ALTER TABLE {table} '
            f'ALTER COLUMN "{column}" TYPE TIMESTAMP WITHOUT TIME ZONE '
            f'USING "{column}" AT TIME ZONE \'UTC\''
        )
