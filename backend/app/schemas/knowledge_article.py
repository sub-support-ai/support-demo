from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.constants.departments import DepartmentLiteral

AccessScopeLiteral = Literal["public", "internal"]
KnowledgeFeedbackLiteral = Literal["helped", "not_helped", "not_relevant"]
KnowledgeDecisionLiteral = Literal["answer", "clarify", "escalate"]


class KnowledgeArticleBase(BaseModel):
    department: DepartmentLiteral | None = None
    request_type: str | None = Field(default=None, max_length=50)
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=8000)
    problem: str | None = Field(default=None, max_length=4000)
    symptoms: list[str] | None = None
    applies_to: dict[str, list[str]] | None = None
    steps: list[str] | None = None
    when_to_escalate: str | None = Field(default=None, max_length=4000)
    required_context: list[str] | None = None
    keywords: str | None = Field(default=None, max_length=2000)
    source_url: str | None = Field(default=None, max_length=500)
    owner: str | None = Field(default=None, max_length=120)
    access_scope: AccessScopeLiteral = "public"
    version: int = Field(default=1, ge=1)
    reviewed_at: datetime | None = None
    expires_at: datetime | None = None
    is_active: bool = True

    @field_validator("request_type", "problem", "when_to_escalate", "keywords", "source_url", "owner")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("symptoms", "steps", "required_context")
    @classmethod
    def strip_text_list(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [item.strip() for item in value if item.strip()]
        return cleaned or None

    @field_validator("applies_to")
    @classmethod
    def strip_applies_to(cls, value: dict[str, list[str]] | None) -> dict[str, list[str]] | None:
        if value is None:
            return None
        cleaned: dict[str, list[str]] = {}
        for key, items in value.items():
            clean_key = key.strip()
            clean_items = [item.strip() for item in items if item.strip()]
            if clean_key and clean_items:
                cleaned[clean_key] = clean_items
        return cleaned or None

    @field_validator("title", "body")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field must not be empty")
        return value


class KnowledgeArticleCreate(KnowledgeArticleBase):
    pass


class KnowledgeArticleUpdate(BaseModel):
    department: DepartmentLiteral | None = None
    request_type: str | None = Field(default=None, max_length=50)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    body: str | None = Field(default=None, min_length=1, max_length=8000)
    problem: str | None = Field(default=None, max_length=4000)
    symptoms: list[str] | None = None
    applies_to: dict[str, list[str]] | None = None
    steps: list[str] | None = None
    when_to_escalate: str | None = Field(default=None, max_length=4000)
    required_context: list[str] | None = None
    keywords: str | None = Field(default=None, max_length=2000)
    source_url: str | None = Field(default=None, max_length=500)
    owner: str | None = Field(default=None, max_length=120)
    access_scope: AccessScopeLiteral | None = None
    version: int | None = Field(default=None, ge=1)
    reviewed_at: datetime | None = None
    expires_at: datetime | None = None
    is_active: bool | None = None

    @field_validator("request_type", "problem", "when_to_escalate", "keywords", "source_url", "owner")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("title", "body")
    @classmethod
    def strip_required_update_text(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Field must not be empty")
        value = value.strip()
        if not value:
            raise ValueError("Field must not be empty")
        return value

    @field_validator("symptoms", "steps", "required_context")
    @classmethod
    def strip_text_list(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [item.strip() for item in value if item.strip()]
        return cleaned or None

    @field_validator("applies_to")
    @classmethod
    def strip_applies_to(cls, value: dict[str, list[str]] | None) -> dict[str, list[str]] | None:
        if value is None:
            return None
        cleaned: dict[str, list[str]] = {}
        for key, items in value.items():
            clean_key = key.strip()
            clean_items = [item.strip() for item in items if item.strip()]
            if clean_key and clean_items:
                cleaned[clean_key] = clean_items
        return cleaned or None


class KnowledgeArticleRead(KnowledgeArticleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    view_count: int = 0
    helped_count: int = 0
    not_helped_count: int = 0
    not_relevant_count: int = 0
    created_at: datetime
    updated_at: datetime | None = None


class KnowledgeArticleMatch(KnowledgeArticleRead):
    score: float
    decision: KnowledgeDecisionLiteral = "answer"
    chunk_id: int | None = None
    snippet: str | None = None
    retrieval: str | None = None


class KnowledgeFeedbackCreate(BaseModel):
    message_id: int
    article_id: int
    feedback: KnowledgeFeedbackLiteral


class KnowledgeFeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    article_id: int
    conversation_id: int
    message_id: int | None = None
    score: float
    decision: str
    feedback: str | None = None
    escalated_ticket_id: int | None = None
    created_at: datetime
    updated_at: datetime | None = None


class KnowledgeEmbeddingJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    article_id: int | None = None
    requested_by_user_id: int | None = None
    status: str
    attempts: int = 0
    max_attempts: int = 3
    updated_chunks: int = 0
    embedding_model: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
