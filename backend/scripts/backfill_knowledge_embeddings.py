import argparse
import asyncio

from app.database import AsyncSessionLocal
from app.services.knowledge_embedding_jobs import embed_pending_knowledge_chunks
from app.services.knowledge_embeddings import (
    DEFAULT_EMBEDDING_BATCH_SIZE,
)


async def backfill_knowledge_embeddings(
    batch_size: int = DEFAULT_EMBEDDING_BATCH_SIZE,
    max_batches: int | None = None,
) -> tuple[int, str | None]:
    async with AsyncSessionLocal() as db:
        updated, embedding_model = await embed_pending_knowledge_chunks(
            db,
            batch_size=batch_size,
            max_batches=max_batches,
        )
        await db.commit()
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
