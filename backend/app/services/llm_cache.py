"""In-memory LRU+TTL кэш для get_ai_answer (LLM-ответов чат-бота).

Зачем кэш именно для LLM:
  - LLM-вызов на CPU — самый медленный шаг пайплайна (10–60 секунд).
  - В саппорте часто одни и те же вопросы: «как сбросить пароль»,
    «не работает VPN», «как взять отпуск».
  - Хороший RAG-hit — мгновенный ответ, без LLM (и без кэша).
  - Если RAG промахнулся → идём в LLM. Здесь кэш и сидит: сохраняем
    ответ модели, на следующий идентичный запрос отдаём instant.

Что кэшируем:
  - Ключ: SHA256(нормализованная история сообщений).
  - Значение: полный ответ get_ai_answer (answer/confidence/escalate/sources/...)

Когда НЕ кэшируем (см. вызывающий код в conversation_ai.py):
  - fallback-ответы (AI service down) — там FALLBACK_REASON_PAYLOAD_KEY,
    смысла кэшировать нет, мы хотим в следующий раз попытаться снова.
  - Низкая уверенность модели (confidence < red_zone) — это значит
    модель сама не знает; кэшировать сомнительный ответ опасно.

Размер и TTL:
  - max_entries=200 — типичная компания за час задаёт <200 уникальных
    вопросов. 200 × ~3 КБ = 600 КБ на воркер.
  - ttl=3600s (1 час) — модель и KB меняются не чаще раза в день;
    свежий ответ за 1 час всё ещё актуален. На дольше держать опасно
    из-за устаревания.

Замер выгоды:
  - На cache-hit отдаём за ~1 мс (vs 10–60 сек на CPU).
  - В payload помечаем _cache_hit=True — это позволяет AILog'у
    отличить «настоящий» ответ модели от кэшированного при анализе
    метрик (среднее время ответа модели нужно считать без cache-hit'ов,
    иначе цифра будет вранливо хорошая).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

CACHE_HIT_PAYLOAD_KEY = "_cache_hit"

# Час — баланс между «свежесть KB-ответов» и «реальный win на повторных
# вопросах в течение рабочей сессии». Если у клиента KB обновляется
# редко — можно повысить через env (см. get_settings ниже, при желании).
DEFAULT_TTL_SECONDS = 3600
DEFAULT_MAX_ENTRIES = 200


@dataclass
class _CacheEntry:
    expires_at: float
    payload: dict[str, Any]


class LLMAnswerCache:
    """LRU+TTL кэш по хэшу истории сообщений.

    Хранит готовый payload get_ai_answer(). На hit обогащает копию
    флагом _cache_hit=True (а не мутирует оригинал в кэше).
    """

    def __init__(
        self,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._store: OrderedDict[str, _CacheEntry] = OrderedDict()

    @staticmethod
    def make_key(messages: list[dict[str, str]]) -> str:
        """Нормализованный ключ.

        - Каждое сообщение приводится к (role, content.strip().lower()).
        - JSON-сериализация с sort_keys=True для стабильности.
        - SHA256 hex — компактный fixed-length ключ (32 байта).

        Чувствителен к ролям: смена user→assistant даст другой ключ.
        Не чувствителен к незначительным правкам капса/whitespace —
        это и нужно: «Не работает VPN» и «не работает vpn» дадут
        одинаковый кэш-hit.
        """
        normalized = [
            {
                "role": m.get("role", ""),
                "content": " ".join((m.get("content") or "").lower().split()),
            }
            for m in messages
        ]
        raw = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, messages: list[dict[str, str]]) -> dict[str, Any] | None:
        key = self.make_key(messages)
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.monotonic():
            # Lazy-eviction по TTL — не запускаем фоновую очистку,
            # просто удаляем при первом обращении после истечения.
            self._store.pop(key, None)
            return None
        # LRU-обновление
        self._store.move_to_end(key)
        # Возвращаем КОПИЮ + помечаем cache_hit. Не мутируем оригинал
        # в кэше, чтобы при множественных hit'ах не накапливать флаги.
        result = dict(entry.payload)
        result[CACHE_HIT_PAYLOAD_KEY] = True
        return result

    def put(self, messages: list[dict[str, str]], payload: dict[str, Any]) -> None:
        key = self.make_key(messages)
        # Сохраняем копию payload без _cache_hit (его доб'aвляет get).
        clean = {k: v for k, v in payload.items() if k != CACHE_HIT_PAYLOAD_KEY}
        self._store[key] = _CacheEntry(
            expires_at=time.monotonic() + self._ttl,
            payload=clean,
        )
        self._store.move_to_end(key)
        # Вытеснение по LRU
        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


# Глобальный инстанс — на воркер. В multi-worker сетапе у каждого свой
# (это нормально, как и для knowledge_cache). Если потребуется разделять
# между воркерами — переехать на Redis.
_cache = LLMAnswerCache()


def get_llm_cache() -> LLMAnswerCache:
    return _cache


def is_cacheable(payload: dict[str, Any], red_zone_threshold: float) -> bool:
    """Решает, можно ли класть ответ модели в кэш.

    НЕ кэшируем:
      - fallback-ответы (AI service down) — _fallback_reason проставлен.
      - Низкая уверенность модели — confidence < red_zone. Кэшировать
        неуверенный ответ значит выдавать его повторно вместо повторной
        попытки модели.
      - Пустой answer — какие-то fallback-варианты.
      - escalate=True — модель явно сказала «нужен агент», а не дала
        полезный ответ. Кэшировать «нужен агент» бесполезно: следующий
        пользователь тоже его получит, но мы потеряем шанс на нормальный
        ответ при ретрае.

    Эти правила — консервативные, лучше не кэшировать что-то спорное
    и потратить лишние секунды LLM, чем выдать кэшированный плохой
    ответ.
    """
    from app.services.ai_fallback import FALLBACK_REASON_PAYLOAD_KEY

    if payload.get(FALLBACK_REASON_PAYLOAD_KEY):
        return False
    if payload.get("escalate"):
        return False
    answer = payload.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return False
    confidence = payload.get("confidence")
    if isinstance(confidence, (int, float)) and confidence < red_zone_threshold:
        return False
    return True
