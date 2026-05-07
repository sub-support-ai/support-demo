import argparse
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import AsyncSessionLocal
from app.models.knowledge_article import KnowledgeChunk
from app.services.knowledge_embeddings import (
    DEFAULT_EMBEDDING_BATCH_SIZE,
    embed_texts,
    mark_chunk_embedded,
    needs_embedding,
    vector_literal,
)


async def _pgvector_available(db: AsyncSession) -> bool:
    if db.get_bind().dialect.name != "postgresql":
        return False
    result = await db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'knowledge_chunks'
                  AND column_name = 'embedding'
            )
            """
        )
    )
    return bool(result.scalar_one())


async def _load_batch(
    db: AsyncSession,
    model: str | None,
    limit: int,
    has_pgvector: bool,
) -> list[KnowledgeChunk]:
    if has_pgvector:
        if model:
            result = await db.execute(
                text(
                    """
                    SELECT id
                    FROM knowledge_chunks
                    WHERE is_active IS TRUE
                      AND (
                        embedding IS NULL
                        OR embedding_model IS NULL
                        OR embedding_model != :model
                        OR embedding_updated_at IS NULL
                      )
                    ORDER BY id ASC
                    LIMIT :limit
                    """
                ),
                {"model": model, "limit": limit},
            )
        else:
            result = await db.execute(
                text(
                    """
                    SELECT id
                    FROM knowledge_chunks
                    WHERE is_active IS TRUE
                      AND (
                        embedding IS NULL
                        OR embedding_model IS NULL
                        OR embedding_updated_at IS NULL
                      )
                    ORDER BY id ASC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
        chunk_ids = [row[0] for row in result.all()]
        if not chunk_ids:
            return []
        chunks_result = await db.execute(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.id.in_(chunk_ids))
            .order_by(KnowledgeChunk.id.asc())
        )
        return chunks_result.scalars().all()

    statement = (
        select(KnowledgeChunk)
        .where(KnowledgeChunk.is_active.is_(True))
        .order_by(KnowledgeChunk.id.asc())
        .limit(limit)
    )
    if model:
        statement = statement.where(
            (KnowledgeChunk.embedding_model.is_(None))
            | (KnowledgeChunk.embedding_model != model)
            | (KnowledgeChunk.embedding_updated_at.is_(None))
        )
    result = await db.execute(statement)
    chunks = result.scalars().all()
    if model:
        return chunks
    return [chunk for chunk in chunks if not chunk.embedding_model or not chunk.embedding_updated_at]


async def backfill_knowledge_embeddings(
    batch_size: int = DEFAULT_EMBEDDING_BATCH_SIZE,
    max_batches: int | None = None,
) -> tuple[int, str | None]:
    updated = 0
    embedding_model: str | None = None

    async with AsyncSessionLocal() as db:
        has_pgvector = await _pgvector_available(db)
        batch_number = 0
        while max_batches is None or batch_number < max_batches:
            chunks = await _load_batch(db, embedding_model, batch_size, has_pgvector)
            if not chunks:
                break

            batch = await embed_texts([chunk.content for chunk in chunks])
            embedding_model = batch.model
            for chunk, embedding in zip(chunks, batch.embeddings, strict=True):
                if not has_pgvector and not needs_embedding(chunk, embedding_model):
                    continue
                mark_chunk_embedded(chunk, embedding_model)
                if has_pgvector:
                    await db.execute(
                        text(
                            """
                            UPDATE knowledge_chunks
                            SET embedding = CAST(:embedding AS vector)
                            WHERE id = :chunk_id
                            """
                        ),
                        {
                            "chunk_id": chunk.id,
                            "embedding": vector_literal(embedding),
                        },
                    )
                updated += 1

            await db.commit()
            batch_number += 1

    return updated, embedding_model


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=DEFAULT_EMBEDDING_BATCH_SIZE)
    parser.add_argument("--max-batches", type=int, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    count, model = asyncio.run(
        backfill_knowledge_embeddings(
            batch_size=args.batch_size,
            max_batches=args.max_batches,
        )
    )
    print(f"Knowledge chunk embeddings updated: {count}. Model: {model or 'none'}.")
