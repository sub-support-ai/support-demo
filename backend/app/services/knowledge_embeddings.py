from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.config import get_settings
from app.models.knowledge_article import KnowledgeChunk

DEFAULT_EMBEDDING_BATCH_SIZE = 16
DEFAULT_EMBEDDING_DIMENSION = 768


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


async def embed_texts(texts: list[str]) -> EmbeddingBatch:
    clean_texts = [text.strip() for text in texts if text.strip()]
    if not clean_texts:
        return EmbeddingBatch(model="", embeddings=[])

    settings = get_settings()
    async with httpx.AsyncClient(timeout=settings.AI_SERVICE_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{settings.AI_SERVICE_URL.rstrip('/')}/ai/embed",
            json={"texts": clean_texts},
        )
        response.raise_for_status()
        payload = response.json()

    model = str(payload.get("model") or "")
    embeddings = payload.get("embeddings")
    if not model or not isinstance(embeddings, list) or len(embeddings) != len(clean_texts):
        raise ValueError("Invalid embedding response")

    normalized: list[list[float]] = []
    for embedding in embeddings:
        if not isinstance(embedding, list) or not embedding:
            raise ValueError("Invalid embedding vector")
        normalized.append([float(value) for value in embedding])

    return EmbeddingBatch(model=model, embeddings=normalized)


def mark_chunk_embedded(chunk: KnowledgeChunk, model: str) -> None:
    chunk.embedding_model = model
    chunk.embedding_updated_at = datetime.now(timezone.utc)
    chunk.token_count = estimate_token_count(chunk.content)
