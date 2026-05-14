"""Сидер базы знаний из JSON-файлов в `seed_data/articles/<department>.json`.

Зачем JSON, а не Python-список:
  1) Тот же формат используется импортёрами из MD/CSV — одна валидация,
     один upsert (см. app/services/knowledge_ingestion.py);
  2) При замене на реальные данные клиента (Confluence/SharePoint/ServiceNow)
     ETL пишет тот же JSON — никаких Python-правок не нужно;
  3) Админу проще ревьюить контент в JSON, чем в питоновских dict-ах
     с экранированием.

Зачем разбито по отделам (it.json, hr.json, …):
  - на больших объёмах удобнее держать отдельный файл на отдел
    (вотчинно: HR-команда правит свой hr.json, не трогая остальные);
  - синхронно с расширенной таксономией (см. app/constants/departments.py).

Идемпотентность: статьи матчатся по title (см. upsert_knowledge_article).
Скрипт можно запускать сколько угодно — дубликатов не будет.

ВАЖНО: эта база — синтетическая, для MVP/демо. При внедрении к клиенту
заменяется на статьи из его источников — см.
backend/scripts/import_knowledge_from_markdown.py
backend/scripts/import_knowledge_from_csv.py
"""

import asyncio
import json
import logging
from pathlib import Path

from app.database import AsyncSessionLocal
from app.services.knowledge_ingestion import bulk_upsert_knowledge_articles

logger = logging.getLogger(__name__)

ARTICLES_DIR = Path(__file__).parent / "seed_data" / "articles"


def _load_articles_from_jsons() -> list[dict]:
    """Читает все *.json из seed_data/articles/ и собирает в один список.

    Невалидный JSON — фейлим громко, лучше упасть на сидинге, чем тихо
    проигнорировать половину статей.
    """
    if not ARTICLES_DIR.exists():
        raise FileNotFoundError(
            f"Папка с seed-статьями не найдена: {ARTICLES_DIR}. "
            "Эту папку коммитим в репо вместе с кодом — проверь, что не "
            "удалили случайно."
        )

    articles: list[dict] = []
    for path in sorted(ARTICLES_DIR.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(f"{path.name}: ожидался список статей в корне JSON")
        logger.info("Loaded %d articles from %s", len(data), path.name)
        articles.extend(data)
    return articles


async def seed_knowledge_articles() -> None:
    articles = _load_articles_from_jsons()
    if not articles:
        print("seed_knowledge_articles: статей не найдено — нечего сидить.")
        return

    async with AsyncSessionLocal() as db:
        created, updated = await bulk_upsert_knowledge_articles(db, articles)
        await db.commit()

    print(f"Knowledge articles ready: total={len(articles)}, created={created}, updated={updated}.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(seed_knowledge_articles())
