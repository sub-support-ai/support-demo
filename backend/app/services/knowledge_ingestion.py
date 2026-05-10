"""Единая точка вставки KnowledgeArticle из любого источника.

Используется тремя путями ingestion'а:
  1) seed_knowledge_articles.py — синтетическая база MVP из data/articles/*.json;
  2) import_knowledge_from_markdown.py — папка с MD-файлами (Confluence-export);
  3) import_knowledge_from_csv.py — CSV-выгрузки из ServiceNow / SharePoint List.

Зачем единая точка:
  - все три источника попадают в одну и ту же таблицу через одинаковую
    upsert-логику (по title как natural key);
  - один канонический набор полей и одна валидация;
  - одна точка для side-effects: sync_knowledge_article_index +
    enqueue_knowledge_embedding_job + cache invalidation.

Идемпотентность: статьи матчатся по `title`. Если запустить импорт второй
раз — те же статьи обновятся, новых дубликатов не появится.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.departments import DEPARTMENTS_SET
from app.models.knowledge_article import KnowledgeArticle
from app.services.knowledge_base import sync_knowledge_article_index
from app.services.knowledge_cache import get_knowledge_cache
from app.services.knowledge_embedding_jobs import enqueue_knowledge_embedding_job

logger = logging.getLogger(__name__)


# Дефолтный TTL для статей, импортируемых из синтетических источников
# (MVP-сид). Статьи, импортируемые из реальных источников клиента,
# должны идти со своим reviewed_at/expires_at — обычно проставляется
# ETL-пайплайном по дате последней правки в Confluence/SharePoint.
DEFAULT_FRESHNESS_DAYS = 180


# Поля, которые принимает upsert. Всё, что приходит сверху, отбрасываем —
# это защищает от случайного попадания служебных полей вроде
# `created_at`/`view_count` из CSV в ORM-объект.
_ALLOWED_FIELDS: tuple[str, ...] = (
    "department",
    "request_type",
    "title",
    "body",
    "problem",
    "symptoms",
    "applies_to",
    "steps",
    "when_to_escalate",
    "required_context",
    "keywords",
    "source_url",
    "owner",
    "access_scope",
    "version",
    "reviewed_at",
    "expires_at",
    "is_active",
)


def _filter_fields(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key in _ALLOWED_FIELDS}


def _validate(item: dict[str, Any]) -> None:
    """Минимум проверок на уровне ingestion'а.

    БД-CHECK всё равно сработает на department, и Pydantic-схемы — на
    POST /knowledge/, но импорт идёт мимо HTTP, и хочется поймать
    типичные ошибки (отсутствует title, неизвестный department) ДО
    INSERT'а с понятным сообщением, а не из глубин SQLAlchemy.
    """
    if not item.get("title"):
        raise ValueError("article must have non-empty 'title'")
    department = item.get("department")
    if department is not None and department not in DEPARTMENTS_SET:
        raise ValueError(
            f"unknown department {department!r}, must be one of {sorted(DEPARTMENTS_SET)}"
        )
    if not item.get("body"):
        raise ValueError(f"article {item['title']!r} must have non-empty 'body'")


def _ensure_freshness(item: dict[str, Any]) -> dict[str, Any]:
    """Если у статьи нет reviewed_at/expires_at — проставляем default'ы.

    Нужно, чтобы синтетические seed-статьи не выглядели «ископаемыми» в
    глазах _freshness_score (там старые статьи штрафуются). Реальные
    статьи приходят с этими полями из источника.
    """
    now = datetime.now(timezone.utc)
    item = dict(item)  # не мутируем входящий dict
    item.setdefault("reviewed_at", now)
    item.setdefault("expires_at", now + timedelta(days=DEFAULT_FRESHNESS_DAYS))
    item.setdefault("version", 1)
    item.setdefault("is_active", True)
    return item


async def upsert_knowledge_article(
    db: AsyncSession,
    item: dict[str, Any],
    *,
    requested_by_user_id: int | None = None,
) -> tuple[KnowledgeArticle, bool]:
    """Создаёт или обновляет статью по title.

    Возвращает (article, created) — created=True значит вставили новую,
    False — обновили существующую. Sync index + embedding job
    запускаются всегда: на новой статье очевидно нужно, на обновлённой
    мог поменяться текст → embedding протух.
    """
    _validate(item)
    item = _ensure_freshness(item)
    item = _filter_fields(item)

    existing = await db.execute(
        select(KnowledgeArticle).where(KnowledgeArticle.title == item["title"])
    )
    article = existing.scalar_one_or_none()
    created = article is None

    if article is None:
        article = KnowledgeArticle(**item)
        db.add(article)
    else:
        for key, value in item.items():
            setattr(article, key, value)

    await db.flush()
    await sync_knowledge_article_index(db, article)
    await enqueue_knowledge_embedding_job(
        db,
        article_id=article.id,
        requested_by_user_id=requested_by_user_id,
    )
    return article, created


async def bulk_upsert_knowledge_articles(
    db: AsyncSession,
    items: Iterable[dict[str, Any]],
    *,
    requested_by_user_id: int | None = None,
) -> tuple[int, int]:
    """Вставляет/обновляет пачку статей в одной транзакции.

    Возвращает (created, updated). Cache сбрасывается ОДИН раз в конце —
    дешевле, чем после каждой статьи.
    """
    created = 0
    updated = 0
    for item in items:
        _, was_created = await upsert_knowledge_article(
            db,
            item,
            requested_by_user_id=requested_by_user_id,
        )
        if was_created:
            created += 1
        else:
            updated += 1

    # Один сброс кэша на весь батч.
    get_knowledge_cache().clear()
    return created, updated
