import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from app.config import get_settings
from app.models.knowledge_article import KnowledgeChunk
from app.services.ai_service_client import ai_service_headers

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_BATCH_SIZE = 16
DEFAULT_EMBEDDING_DIMENSION = 768

# Сетевой ретрай для embed:
#   - Ollama под нагрузкой иногда отдаёт 502/таймаут на отдельные запросы;
#   - один сбой не должен валить весь embedding-batch (а с ним — пересчёт
#     эмбеддингов всего набора чанков);
#   - 3 попытки с экспоненциальным backoff'ом — достаточно по эмпирике,
#     дальше — реальная недоступность сервиса, нет смысла ждать.
_EMBED_MAX_ATTEMPTS = 3
_EMBED_BACKOFF_BASE_SECONDS = 0.5


@dataclass(frozen=True)
class EmbeddingBatch:
    model: str
    embeddings: list[list[float]]


def estimate_token_count(text: str) -> int:
    return max(1, len(text.split()))


def needs_embedding(chunk: KnowledgeChunk, model: str) -> bool:
    return (
        not chunk.embedding_model
        or chunk.embedding_model != model
        or chunk.embedding_updated_at is None
    )


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"


async def _post_embed(texts: list[str]) -> dict:
    """Один сетевой вызов /ai/embed. Выделено для ретрая (см. embed_texts)."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=settings.AI_SERVICE_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{settings.AI_SERVICE_URL.rstrip('/')}/ai/embed",
            headers=ai_service_headers(),
            json={"texts": texts},
        )
        response.raise_for_status()
        return response.json()


async def embed_texts(texts: list[str]) -> EmbeddingBatch:
    """Запрашивает эмбеддинги через AI-сервис с дедупликацией и ретраями.

    Дедупликация:
      - в один батч часто приходят повторяющиеся тексты (например, мы
        переиндексируем кучу чанков, и одинаковые fragments — типичны).
      - отправляем уникальные тексты, потом раскладываем эмбеддинги
        обратно по индексам входа.
      - экономит ~30-40% RPC к Ollama на больших партиях.

    Ретраи:
      - на сетевые ошибки/5xx делаем до _EMBED_MAX_ATTEMPTS попыток
        с экспоненциальным backoff'ом (0.5s, 1s, 2s).
      - на 4xx и broken JSON ретраим тоже — Ollama иногда отдаёт битые
        ответы под нагрузкой, повтор обычно проходит.
      - после исчерпания попыток — пробрасываем последнее исключение
        наверх (вызывающий код сам решит, fallback или raise).
    """
    clean_texts = [text.strip() for text in texts if text.strip()]
    if not clean_texts:
        return EmbeddingBatch(model="", embeddings=[])

    # Дедупликация: маппинг уникальный-текст → индекс в unique_texts
    unique_texts: list[str] = []
    text_to_index: dict[str, int] = {}
    for text in clean_texts:
        if text not in text_to_index:
            text_to_index[text] = len(unique_texts)
            unique_texts.append(text)

    last_exc: Exception | None = None
    payload: dict | None = None
    for attempt in range(1, _EMBED_MAX_ATTEMPTS + 1):
        try:
            payload = await _post_embed(unique_texts)
            break
        except (httpx.HTTPError, ValueError) as exc:
            last_exc = exc
            if attempt < _EMBED_MAX_ATTEMPTS:
                # Экспоненциальный backoff: 0.5, 1, 2 секунды.
                delay = _EMBED_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "embed_texts attempt %d/%d failed (%s), retrying in %.1fs",
                    attempt,
                    _EMBED_MAX_ATTEMPTS,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "embed_texts failed after %d attempts: %s",
                    _EMBED_MAX_ATTEMPTS,
                    exc,
                )
    if payload is None:
        # Все попытки провалились — пробрасываем последнюю ошибку.
        # Вызывающий код (knowledge_base._search_..._semantic_postgres)
        # ловит Exception и тихо деградирует на FTS-only.
        assert last_exc is not None  # для type checker'а
        raise last_exc

    model = str(payload.get("model") or "")
    embeddings = payload.get("embeddings")
    if not model or not isinstance(embeddings, list) or len(embeddings) != len(unique_texts):
        raise ValueError("Invalid embedding response")

    # Нормализация: каждый эмбеддинг — list[float], непустой.
    normalized_unique: list[list[float]] = []
    for embedding in embeddings:
        if not isinstance(embedding, list) or not embedding:
            raise ValueError("Invalid embedding vector")
        normalized_unique.append([float(value) for value in embedding])

    # Раскладываем обратно по индексам входа.
    result = [normalized_unique[text_to_index[text]] for text in clean_texts]

    return EmbeddingBatch(model=model, embeddings=result)


def mark_chunk_embedded(chunk: KnowledgeChunk, model: str) -> None:
    chunk.embedding_model = model
    chunk.embedding_updated_at = datetime.now(UTC)
    chunk.token_count = estimate_token_count(chunk.content)
