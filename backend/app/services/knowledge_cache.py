"""In-memory LRU+TTL кэш для search_knowledge_articles.

Зачем кэш:
  - на типовых вопросах ("как сбросить пароль", "не работает VPN")
    в течение часа приходят десятки одинаковых запросов;
  - каждый поход в FTS + pgvector + scoring = ~50-150 мс на postgres'е,
    плюс 1 RPC-вызов на эмбеддинг через Ollama (~30-100 мс);
  - на полностью одинаковом нормализованном query/фильтре результат
    меняется только при правках статей или росте feedback'а (то и то
    редко относительно частоты запросов).

Что НЕ кэшируем:
  - LLM-ответы (build_knowledge_answer) — там есть _latency_ms, который
    важно мерить честно для пианино метрик «AI отвечает за 1 сек»;
  - результат hybrid-merge с разной выдачей FTS/semantic — кэш сидит
    выше, на verkhнем уровне search_knowledge_articles, и ловит итоговый
    список Match'ей.

Почему in-memory, а не Redis:
  - кэш короткоживущий (TTL 60с), вытесняется LRU при росте >100 записей;
  - в multi-worker uvicorn-сетапе каждый worker имеет свою копию — это
    допустимо, потому что cache-miss дёшев, а консистентности между
    воркерами для приближённого RAG-результата не требуется;
  - Redis-кэш — отдельная задача (когда захотим shared invalidation
    при правках KB-статей, см. todo «cross-worker cache invalidation»).

Безопасность объектов:
  - KnowledgeMatch содержит ORM KnowledgeArticle. До помещения в кэш
    мы НЕ делаем expunge — объект просто detach'ится естественным образом
    после закрытия сессии. На cache-hit мы возвращаем тот же объект —
    его атрибуты (title, body, ...) уже загружены и доступны без сессии.
    Если admin поменял статью за время TTL — клиент увидит устаревшую
    версию максимум 60 секунд (приемлемо для RAG).

Конкурентность:
  - asyncio в одном процессе работает в одном потоке, dict-операции
    между await атомарны. Lock не нужен.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.knowledge_base import KnowledgeMatch, KnowledgeSearchFilters

logger = logging.getLogger(__name__)

# 60 сек — компромисс между «пользователь видит свежие правки» и «ловим
# вспышки повторных вопросов» (типичный пик одинаковых запросов в чате
# службы поддержки длится 5-30 секунд).
DEFAULT_TTL_SECONDS = 60

# 100 записей при ~5 КБ каждая = ~500 КБ на воркер, безопасно. LRU
# гарантирует, что редкие запросы вытесняются частыми, а не наоборот.
DEFAULT_MAX_ENTRIES = 100


@dataclass
class _CacheEntry:
    expires_at: float
    matches: list["KnowledgeMatch"]


class KnowledgeSearchCache:
    """LRU+TTL кэш для результатов search_knowledge_articles.

    Класс выделен (а не модульные функции с глобальным OrderedDict),
    чтобы тесты могли создавать изолированные инстансы без обхода глобала.
    """

    def __init__(
        self,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._store: OrderedDict[tuple, _CacheEntry] = OrderedDict()

    @staticmethod
    def _make_key(
        query: str,
        limit: int,
        filters: "KnowledgeSearchFilters",
    ) -> tuple:
        """Стабильный ключ. query нормализуется (lowercase + collapse whitespace).

        access_scopes уже tuple (frozen в KnowledgeSearchFilters), поэтому
        хешируется без преобразований.
        """
        normalized_query = " ".join(query.lower().split())
        return (
            normalized_query,
            limit,
            filters.department,
            filters.request_type,
            filters.office,
            filters.system,
            filters.device,
            filters.access_scopes,
        )

    def get(
        self,
        query: str,
        limit: int,
        filters: "KnowledgeSearchFilters",
    ) -> list["KnowledgeMatch"] | None:
        key = self._make_key(query, limit, filters)
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.monotonic():
            # Lazy eviction по TTL — не пытаемся удалять "по таймеру".
            self._store.pop(key, None)
            return None
        # LRU: тронули → переместили в конец (most-recently-used).
        self._store.move_to_end(key)
        return entry.matches

    def put(
        self,
        query: str,
        limit: int,
        filters: "KnowledgeSearchFilters",
        matches: list["KnowledgeMatch"],
    ) -> None:
        key = self._make_key(query, limit, filters)
        self._store[key] = _CacheEntry(
            expires_at=time.monotonic() + self._ttl,
            matches=matches,
        )
        self._store.move_to_end(key)
        # Вытеснение по LRU
        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)

    def clear(self) -> None:
        """Полная очистка. Зовётся тестами и (опционально) при правках KB."""
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


# Глобальный инстанс. На время тестов KB-search можно очищать через
# get_knowledge_cache().clear() в фикстурах.
_cache = KnowledgeSearchCache()


def get_knowledge_cache() -> KnowledgeSearchCache:
    return _cache
