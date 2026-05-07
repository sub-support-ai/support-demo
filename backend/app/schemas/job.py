from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AIJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    status: str
    attempts: int
    max_attempts: int
    error: str | None = None
    run_after: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class KnowledgeEmbeddingJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    article_id: int | None = None
    requested_by_user_id: int | None = None
    status: str
    attempts: int
    max_attempts: int
    updated_chunks: int
    embedding_model: str | None = None
    error: str | None = None
    run_after: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class FailedJobsResponse(BaseModel):
    ai: list[AIJobRead]
    knowledge_embeddings: list[KnowledgeEmbeddingJobRead]


class JobsResponse(BaseModel):
    ai: list[AIJobRead]
    knowledge_embeddings: list[KnowledgeEmbeddingJobRead]
