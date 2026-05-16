"""add quality_grade to knowledge articles + feedback time index

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-05-16 00:00:00.000000

Что делает:
  1. Добавляет колонку `quality_grade` на knowledge_articles:
       'good' | 'risky' | 'bad' | 'suppressed'
     Это «оценка качества» статьи, вычисляемая периодически по feedback.
     По умолчанию 'good' — все существующие статьи получают нейтральный grade.

  2. Добавляет `quality_grade_updated_at` — когда последний раз пересчитывали.
     Нужно для тротлинга фоновой job'ы (не пересчитывать чаще раза в 5 мин).

  3. Создаёт композитный индекс на KnowledgeArticleFeedback(article_id, created_at).
     Critical: для exponential decay-агрегации feedback по статье мы запрашиваем
     ВСЕ её feedback за окно времени. Без индекса — full scan по таблице, которая
     быстро растёт.

  4. CHECK constraint на допустимые значения quality_grade — защита целостности
     от случайных писем с произвольными строками.

Совместимость: использует String(20) + CHECK вместо native ENUM. Это portable
между PostgreSQL и SQLite (SQLite не имеет native ENUM, postgres имеет, но
тогда любое добавление нового grade требует ALTER TYPE — гемор в миграциях).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "m3n4o5p6q7r8"
down_revision: str | None = "l2m3n4o5p6q7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Допустимые значения quality_grade. Меняется в сервисе quality_signals.py.
ALLOWED_GRADES = ("good", "risky", "bad", "suppressed")


def upgrade() -> None:
    # 1. Колонка quality_grade с дефолтом 'good'.
    #    server_default — чтобы существующие строки получили значение без
    #    дополнительного UPDATE; nullable=False — статья без grade невалидна.
    op.add_column(
        "knowledge_articles",
        sa.Column(
            "quality_grade",
            sa.String(length=20),
            nullable=False,
            server_default="good",
        ),
    )

    # 2. Когда последний раз пересчитывали grade. NULL означает «никогда»,
    #    фоновая job обработает такие статьи в первую очередь.
    op.add_column(
        "knowledge_articles",
        sa.Column(
            "quality_grade_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # 2a. Материализованный weighted_feedback_score (диапазон -2.0..+2.0)
    #     рассчитанный с exponential decay. Это «свежий» аналог старой формулы
    #     по счётчикам helped/not_helped. Используется в RAG-ranking как
    #     основной feedback-сигнал.
    #     Обновляется одновременно с quality_grade в refresh_article_quality_grade.
    #     Дефолт 0.0 — нейтральный сигнал для статей, по которым ещё нет данных.
    op.add_column(
        "knowledge_articles",
        sa.Column(
            "weighted_feedback_score",
            sa.Float(),
            nullable=False,
            server_default="0.0",
        ),
    )

    # 3. Индекс на quality_grade — фильтруем по нему в search_knowledge_articles
    #    (исключаем 'bad'/'suppressed' из выдачи). Без индекса — sequential scan
    #    при каждом поиске.
    op.create_index(
        "ix_knowledge_articles_quality_grade",
        "knowledge_articles",
        ["quality_grade"],
    )

    # 4. CHECK constraint — защита от инвалидных значений на уровне БД.
    #    На SQLite в тестах CHECK тоже работает.
    grades_quoted = ", ".join(f"'{g}'" for g in ALLOWED_GRADES)
    op.create_check_constraint(
        "ck_knowledge_articles_quality_grade_valid",
        "knowledge_articles",
        f"quality_grade IN ({grades_quoted})",
    )

    # 5. Композитный индекс на feedback (article_id, created_at) — critical
    #    для decay-агрегации. Запрос вида:
    #      SELECT feedback, created_at FROM knowledge_article_feedbacks
    #      WHERE article_id = ? AND created_at >= ?
    #    использует этот индекс для index-only scan.
    op.create_index(
        "ix_knowledge_article_feedbacks_article_created",
        "knowledge_article_feedbacks",
        ["article_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_article_feedbacks_article_created",
        table_name="knowledge_article_feedbacks",
    )
    op.drop_constraint(
        "ck_knowledge_articles_quality_grade_valid",
        "knowledge_articles",
        type_="check",
    )
    op.drop_index("ix_knowledge_articles_quality_grade", table_name="knowledge_articles")
    op.drop_column("knowledge_articles", "weighted_feedback_score")
    op.drop_column("knowledge_articles", "quality_grade_updated_at")
    op.drop_column("knowledge_articles", "quality_grade")
