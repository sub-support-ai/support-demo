import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import bindparam, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_article import KnowledgeArticle

TOKEN_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9]+")
MEDIUM_SCORE_THRESHOLD = 4.0
HIGH_SCORE_THRESHOLD = 8.0
POSTGRES_FTS_SCORE_WEIGHT = 20.0
POSTGRES_FTS_CANDIDATE_MULTIPLIER = 8

STOP_WORDS = {
    "для",
    "как",
    "или",
    "при",
    "что",
    "это",
    "если",
    "меня",
    "мне",
    "мой",
    "моя",
    "оно",
    "уже",
    "the",
    "and",
    "with",
}


@dataclass(frozen=True)
class KnowledgeSearchFilters:
    department: str | None = None
    request_type: str | None = None
    office: str | None = None
    system: str | None = None
    device: str | None = None
    access_scopes: tuple[str, ...] = ("public",)


@dataclass(frozen=True)
class KnowledgeMatch:
    article: KnowledgeArticle
    score: float
    decision: str


def tokenize(text: str) -> set[str]:
    return {
        token.lower()
        for token in TOKEN_RE.findall(text)
        if len(token) >= 3 and token.lower() not in STOP_WORDS
    }


def _iter_json_values(value: object) -> Iterable[str]:
    if value is None:
        return
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_json_values(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _iter_json_values(item)


def build_search_text(article: KnowledgeArticle) -> str:
    parts = [
        article.title,
        article.body,
        article.problem or "",
        article.when_to_escalate or "",
        article.keywords or "",
        article.request_type or "",
        article.department or "",
    ]
    parts.extend(_iter_json_values(article.symptoms))
    parts.extend(_iter_json_values(article.applies_to))
    parts.extend(_iter_json_values(article.steps))
    parts.extend(_iter_json_values(article.required_context))
    return "\n".join(part for part in parts if part)


def _feedback_score(article: KnowledgeArticle) -> float:
    helped = article.helped_count or 0
    negative = (article.not_helped_count or 0) + (article.not_relevant_count or 0)
    total = helped + negative
    if total == 0:
        return 0.0
    return max(-2.0, min(2.0, (helped - negative) / total * 2))


def _freshness_score(article: KnowledgeArticle, now: datetime) -> float:
    if article.expires_at is not None:
        expires_at = article.expires_at
        if expires_at.tzinfo is None:
            now = now.replace(tzinfo=None)
        if expires_at < now:
            return -3.0

    if article.reviewed_at is None:
        return 0.0

    reviewed_at = article.reviewed_at
    if reviewed_at.tzinfo is None:
        now = now.replace(tzinfo=None)
    age_days = max(0, (now - reviewed_at).days)
    if age_days <= 90:
        return 1.0
    if age_days <= 180:
        return 0.5
    return -0.5


def _context_score(article: KnowledgeArticle, filters: KnowledgeSearchFilters) -> float:
    score = 0.0
    applies_to = article.applies_to or {}
    applies_text = " ".join(_iter_json_values(applies_to)).lower()

    for value in (filters.office, filters.system, filters.device):
        if value and value.lower() in applies_text:
            score += 2.0

    if filters.request_type and article.request_type == filters.request_type:
        score += 2.0
    if filters.department and article.department == filters.department:
        score += 1.0
    return score


def _text_score(query: str, query_tokens: set[str], article: KnowledgeArticle) -> float:
    title = article.title.lower()
    body = article.body.lower()
    problem = (article.problem or "").lower()
    keywords = (article.keywords or "").lower()
    search_text = (article.search_text or build_search_text(article)).lower()
    haystack_tokens = tokenize(search_text)

    score = 0.0
    for token in query_tokens:
        if token in title:
            score += 4.0
        elif token in keywords:
            score += 3.0
        elif token in problem:
            score += 2.0
        elif token in body:
            score += 1.0
        if token in haystack_tokens:
            score += 0.5

    query_lower = query.lower().strip()
    if query_lower and query_lower in title:
        score += 5.0
    if query_lower and query_lower in keywords:
        score += 4.0
    return score


def _decision_for_score(score: float) -> str:
    if score >= HIGH_SCORE_THRESHOLD:
        return "answer"
    if score >= MEDIUM_SCORE_THRESHOLD:
        return "clarify"
    return "escalate"


def _score_article(
    query: str,
    query_tokens: set[str],
    article: KnowledgeArticle,
    filters: KnowledgeSearchFilters,
    now: datetime,
    text_score: float | None = None,
) -> float:
    return (
        (text_score if text_score is not None else _text_score(query, query_tokens, article))
        + _context_score(article, filters)
        + _freshness_score(article, now)
        + _feedback_score(article)
    )


def _apply_common_filters(statement, filters: KnowledgeSearchFilters):
    if filters.access_scopes:
        statement = statement.where(KnowledgeArticle.access_scope.in_(filters.access_scopes))
    if filters.department:
        statement = statement.where(
            or_(
                KnowledgeArticle.department == filters.department,
                KnowledgeArticle.department.is_(None),
            )
        )
    if filters.request_type:
        statement = statement.where(
            or_(
                KnowledgeArticle.request_type == filters.request_type,
                KnowledgeArticle.request_type.is_(None),
            )
        )
    return statement


def _build_matches(
    rows: list[tuple[KnowledgeArticle, float | None]],
    query: str,
    query_tokens: set[str],
    filters: KnowledgeSearchFilters,
    now: datetime,
) -> list[KnowledgeMatch]:
    matches: list[KnowledgeMatch] = []
    for article, postgres_fts_score in rows:
        fallback_text_score = _text_score(query, query_tokens, article)
        if postgres_fts_score is None:
            text_score = fallback_text_score
        else:
            text_score = max(
                fallback_text_score,
                float(postgres_fts_score or 0.0) * POSTGRES_FTS_SCORE_WEIGHT,
            )
        score = _score_article(
            query,
            query_tokens,
            article,
            filters,
            now,
            text_score=text_score,
        )
        if score >= MEDIUM_SCORE_THRESHOLD:
            matches.append(
                KnowledgeMatch(
                    article=article,
                    score=score,
                    decision=_decision_for_score(score),
                )
            )
    matches.sort(key=lambda match: (-match.score, match.article.id))
    return matches


def _session_dialect_name(db: AsyncSession) -> str:
    bind = db.get_bind()
    return bind.dialect.name


async def _search_knowledge_articles_postgres(
    db: AsyncSession,
    query: str,
    query_tokens: set[str],
    limit: int,
    filters: KnowledgeSearchFilters,
) -> list[KnowledgeMatch]:
    search_vector = literal_column("knowledge_articles.search_vector")
    query_param = bindparam("query")
    fts_query = func.websearch_to_tsquery(
        literal_column("'russian'::regconfig"),
        query_param,
    ).op("||")(
        func.websearch_to_tsquery(
            literal_column("'simple'::regconfig"),
            query_param,
        )
    )
    postgres_fts_score = func.ts_rank_cd(search_vector, fts_query).label("postgres_fts_score")
    statement = (
        select(KnowledgeArticle, postgres_fts_score)
        .where(KnowledgeArticle.is_active.is_(True))
        .where(search_vector.op("@@")(fts_query))
    )
    statement = _apply_common_filters(statement, filters)
    statement = statement.order_by(postgres_fts_score.desc(), KnowledgeArticle.id.asc()).limit(
        max(limit * POSTGRES_FTS_CANDIDATE_MULTIPLIER, limit)
    )

    result = await db.execute(statement, {"query": query})
    rows = [(article, score) for article, score in result.all()]
    return _build_matches(
        rows,
        query,
        query_tokens,
        filters,
        datetime.now(timezone.utc),
    )[:limit]


async def _search_knowledge_articles_fallback(
    db: AsyncSession,
    query: str,
    query_tokens: set[str],
    limit: int,
    filters: KnowledgeSearchFilters,
) -> list[KnowledgeMatch]:
    statement = select(KnowledgeArticle).where(KnowledgeArticle.is_active.is_(True))
    statement = _apply_common_filters(statement, filters)

    result = await db.execute(statement.order_by(KnowledgeArticle.id.asc()))
    rows = [(article, None) for article in result.scalars().all()]
    return _build_matches(
        rows,
        query,
        query_tokens,
        filters,
        datetime.now(timezone.utc),
    )[:limit]


async def search_knowledge_articles(
    db: AsyncSession,
    query: str,
    limit: int = 3,
    filters: KnowledgeSearchFilters | None = None,
) -> list[KnowledgeMatch]:
    filters = filters or KnowledgeSearchFilters()
    query = query.strip()
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    if _session_dialect_name(db) == "postgresql":
        return await _search_knowledge_articles_postgres(
            db,
            query,
            query_tokens,
            limit,
            filters,
        )

    return await _search_knowledge_articles_fallback(
        db,
        query,
        query_tokens,
        limit,
        filters,
    )


def _format_steps(article: KnowledgeArticle) -> str:
    steps = article.steps or []
    if steps:
        return "\n".join(f"{index}. {step}" for index, step in enumerate(steps, start=1))
    return article.body


def _format_required_context(article: KnowledgeArticle) -> str:
    fields = article.required_context or []
    if not fields:
        return "офис, устройство или система, код ошибки, что уже пробовали"
    return ", ".join(fields)


def build_knowledge_answer(match: KnowledgeMatch, query: str) -> dict:
    article = match.article
    source = {
        "title": article.title,
        "url": article.source_url,
        "article_id": article.id,
        "score": match.score,
        "decision": match.decision,
    }

    if match.decision == "clarify":
        return {
            "answer": (
                f"Похоже на статью базы знаний: {article.title}.\n\n"
                f"Чтобы дать точный ответ, уточните: {_format_required_context(article)}."
            ),
            "confidence": 0.65,
            "escalate": False,
            "sources": [source],
            "model_version": "knowledge-base-v1",
            "knowledge_article_id": article.id,
            "knowledge_score": match.score,
            "knowledge_decision": match.decision,
            "knowledge_query": query,
        }

    escalation_rule = (
        f"\n\nКогда создавать запрос: {article.when_to_escalate}"
        if article.when_to_escalate
        else ""
    )
    return {
        "answer": (
            f"Нашёл решение в базе знаний: {article.title}\n\n"
            f"{_format_steps(article)}"
            f"{escalation_rule}\n\n"
            "Если это не поможет, нажмите “Не помогло” или напишите, что осталось неработающим."
        ),
        "confidence": min(0.95, 0.7 + match.score / 40),
        "escalate": False,
        "sources": [source],
        "model_version": "knowledge-base-v1",
        "knowledge_article_id": article.id,
        "knowledge_score": match.score,
        "knowledge_decision": match.decision,
        "knowledge_query": query,
    }


async def find_knowledge_answer(
    db: AsyncSession,
    messages: list[dict[str, str]],
) -> dict | None:
    user_messages = [
        message.get("content", "").strip()
        for message in messages
        if message.get("role") == "user" and message.get("content", "").strip()
    ]
    if not user_messages:
        return None

    latest = user_messages[-1]
    combined = "\n".join(user_messages[-3:])
    query = f"{latest}\n{combined}"
    matches = await search_knowledge_articles(db, query, limit=1)
    if not matches:
        return None
    return build_knowledge_answer(matches[0], query)
