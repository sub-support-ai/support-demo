import logging
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from sqlalchemy import bindparam, func, literal_column, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.knowledge_article import KnowledgeArticle, KnowledgeChunk
from app.services.knowledge_embeddings import embed_texts, estimate_token_count, vector_literal

logger = logging.getLogger(__name__)

# Служебный ключ, под которым find_knowledge_answer / get_ai_answer
# (conversation_ai.py) кладут замеренную латенси в payload. Дальше его
# подхватывает generate_ai_message и пишет в AILog.ai_response_time_ms.
# Префикс «_» подчёркивает, что это не часть API-контракта — наружу не уходит.
LATENCY_PAYLOAD_KEY = "_latency_ms"

TOKEN_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9]+")
POSTGRES_FTS_SCORE_WEIGHT = 20.0
POSTGRES_FTS_CANDIDATE_MULTIPLIER = 8
POSTGRES_SEMANTIC_SCORE_WEIGHT = 12.0
POSTGRES_SEMANTIC_CANDIDATE_MULTIPLIER = 8
KNOWLEDGE_CHUNK_TARGET_TOKENS = 220
KNOWLEDGE_CHUNK_OVERLAP_TOKENS = 40

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
    "надо",
    "нужно",
    "хочу",
}

BLOCKING_SYSTEM_ALIASES: dict[str, tuple[str, ...]] = {
    "1c": ("1с", "1c", "1с:", "1c:"),
    "bitlocker": ("bitlocker", "битлокер", "recovery key", "ключ восстановления"),
    "filevault": ("filevault",),
    "vpn": ("vpn", "впн"),
    "wifi": ("wi-fi", "wifi", "вайфай"),
    "printer": ("принтер", "мфу", "печать"),
    "sap": ("sap",),
    "jira": ("jira", "джира"),
    "confluence": ("confluence",),
    "bitrix": ("bitrix", "битрикс"),
}


@dataclass(frozen=True)
class _SystemAlignment:
    reject: bool = False
    cap_to_clarify: bool = False
    score_bonus: float = 0.0


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
    snippet: str | None = None
    chunk_id: int | None = None
    retrieval: str = "keyword"


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


def _normalise_for_system_match(text: str) -> str:
    return " ".join(text.casefold().replace("ё", "е").split())


def _mentioned_blocking_systems(text: str) -> set[str]:
    normalised = _normalise_for_system_match(text)
    if not normalised:
        return set()
    return {
        system
        for system, aliases in BLOCKING_SYSTEM_ALIASES.items()
        if any(alias in normalised for alias in aliases)
    }


def _system_alignment(query: str, article: KnowledgeArticle) -> _SystemAlignment:
    query_systems = _mentioned_blocking_systems(query)
    if not query_systems:
        return _SystemAlignment()

    article_systems = _mentioned_blocking_systems(article.search_text or build_search_text(article))
    if query_systems & article_systems:
        return _SystemAlignment(score_bonus=4.0)
    if article_systems:
        return _SystemAlignment(reject=True)
    return _SystemAlignment(cap_to_clarify=True)


def _section_text(title: str, value: object) -> str | None:
    values = [item.strip() for item in _iter_json_values(value) if item.strip()]
    if not values:
        return None
    return f"{title}:\n" + "\n".join(values)


def build_knowledge_chunk_text(article: KnowledgeArticle) -> str:
    sections = [
        _section_text("Title", article.title),
        _section_text("Problem", article.problem),
        _section_text("Symptoms", article.symptoms),
        _section_text("Applies to", article.applies_to),
        _section_text("Solution", article.steps or article.body),
        _section_text("Escalate when", article.when_to_escalate),
        _section_text("Required context", article.required_context),
        _section_text("Keywords", article.keywords),
    ]
    return "\n\n".join(section for section in sections if section)


def split_knowledge_text(
    text: str,
    target_tokens: int = KNOWLEDGE_CHUNK_TARGET_TOKENS,
    overlap_tokens: int = KNOWLEDGE_CHUNK_OVERLAP_TOKENS,
) -> list[str]:
    words = text.split()
    if not words:
        return []
    if len(words) <= target_tokens:
        return [" ".join(words)]

    chunks: list[str] = []
    step = max(1, target_tokens - overlap_tokens)
    start = 0
    while start < len(words):
        chunk_words = words[start : start + target_tokens]
        chunks.append(" ".join(chunk_words))
        if start + target_tokens >= len(words):
            break
        start += step
    return chunks


async def sync_knowledge_article_index(
    db: AsyncSession,
    article: KnowledgeArticle,
) -> None:
    article.search_text = build_search_text(article)

    desired_chunks = split_knowledge_text(build_knowledge_chunk_text(article))
    result = await db.execute(
        select(KnowledgeChunk)
        .where(KnowledgeChunk.article_id == article.id)
        .order_by(KnowledgeChunk.chunk_index.asc(), KnowledgeChunk.id.asc())
    )
    existing_by_index = {chunk.chunk_index: chunk for chunk in result.scalars().all()}

    for index, content in enumerate(desired_chunks):
        chunk = existing_by_index.get(index)
        if chunk is None:
            db.add(
                KnowledgeChunk(
                    article_id=article.id,
                    chunk_index=index,
                    content=content,
                    token_count=estimate_token_count(content),
                    is_active=True,
                )
            )
            continue

        if chunk.content != content:
            chunk.content = content
            chunk.embedding_model = None
            chunk.embedding_updated_at = None
        chunk.token_count = estimate_token_count(content)
        chunk.is_active = True

    for index, chunk in existing_by_index.items():
        if index >= len(desired_chunks):
            chunk.is_active = False
            chunk.embedding_model = None
            chunk.embedding_updated_at = None


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


def _compact_text(value: str) -> str:
    return " ".join(value.split())


def _excerpt_from_text(
    text: str,
    query_tokens: set[str],
    max_length: int = 360,
) -> str | None:
    text = _compact_text(text)
    if not text:
        return None

    lower_text = text.lower()
    start = 0
    for token in query_tokens:
        index = lower_text.find(token)
        if index >= 0:
            start = max(0, index - 90)
            break

    excerpt = text[start : start + max_length].strip()
    if start > 0:
        excerpt = f"...{excerpt}"
    if start + max_length < len(text):
        excerpt = f"{excerpt}..."
    return excerpt


def _article_snippet(article: KnowledgeArticle, query_tokens: set[str]) -> str | None:
    parts = [
        article.problem or "",
        article.body,
        "\n".join(article.steps or []),
        article.when_to_escalate or "",
    ]
    return _excerpt_from_text("\n".join(part for part in parts if part), query_tokens)


def _decision_for_score(score: float) -> str:
    settings = get_settings()
    if score >= settings.RAG_SCORE_HIGH_THRESHOLD:
        return "answer"
    if score >= settings.RAG_SCORE_MEDIUM_THRESHOLD:
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
    # Expired-статьи отфильтровываем на уровне SQL: _freshness_score штрафует
    # их через -3.0, но они всё равно попадают в кандидаты и могут пройти
    # пороги, если text_score высокий. Лучше не показывать совсем — статья
    # с expires_at в прошлом ≡ «info устарело, не отдавать пользователю».
    # NULL expires_at ≡ «без срока» — оставляем.
    statement = statement.where(
        or_(
            KnowledgeArticle.expires_at.is_(None),
            KnowledgeArticle.expires_at > func.now(),
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
    medium_threshold = get_settings().RAG_SCORE_MEDIUM_THRESHOLD
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
        alignment = _system_alignment(query, article)
        if alignment.reject:
            continue
        score += alignment.score_bonus
        if score >= medium_threshold:
            decision = _decision_for_score(score)
            if alignment.cap_to_clarify and decision == "answer":
                decision = "clarify"
            matches.append(
                KnowledgeMatch(
                    article=article,
                    score=score,
                    decision=decision,
                    snippet=_article_snippet(article, query_tokens),
                    retrieval="full_text" if postgres_fts_score is not None else "keyword",
                )
            )
    matches.sort(key=lambda match: (-match.score, match.article.id))
    return matches


def _session_dialect_name(db: AsyncSession) -> str:
    bind = db.get_bind()
    return bind.dialect.name


def _merge_matches(
    first: list[KnowledgeMatch],
    second: list[KnowledgeMatch],
    limit: int,
) -> list[KnowledgeMatch]:
    by_article_id: dict[int, KnowledgeMatch] = {}
    for match in first + second:
        current = by_article_id.get(match.article.id)
        if current is None or match.score > current.score:
            by_article_id[match.article.id] = match
    matches = sorted(
        by_article_id.values(),
        key=lambda match: (-match.score, match.article.id),
    )
    return matches[:limit]


async def _pgvector_available(db: AsyncSession) -> bool:
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


def _semantic_filter_sql(filters: KnowledgeSearchFilters) -> tuple[str, dict[str, object]]:
    clauses: list[str] = []
    params: dict[str, object] = {}

    if filters.access_scopes:
        placeholders = []
        for index, scope in enumerate(filters.access_scopes):
            key = f"scope_{index}"
            placeholders.append(f":{key}")
            params[key] = scope
        clauses.append(f"ka.access_scope IN ({', '.join(placeholders)})")

    if filters.department:
        clauses.append("(ka.department = :department OR ka.department IS NULL)")
        params["department"] = filters.department

    if filters.request_type:
        clauses.append("(ka.request_type = :request_type OR ka.request_type IS NULL)")
        params["request_type"] = filters.request_type

    # Expired-статьи отбрасываем — синхронно с _apply_common_filters
    # (FTS-путь). NULL expires_at ≡ «без срока», оставляем.
    clauses.append("(ka.expires_at IS NULL OR ka.expires_at > NOW())")

    if not clauses:
        return "", params
    return " AND " + " AND ".join(clauses), params


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
        datetime.now(UTC),
    )[:limit]


async def _search_knowledge_articles_semantic_postgres(
    db: AsyncSession,
    query: str,
    query_tokens: set[str],
    limit: int,
    filters: KnowledgeSearchFilters,
) -> list[KnowledgeMatch]:
    if not get_settings().KNOWLEDGE_SEMANTIC_SEARCH_ENABLED:
        return []
    if not await _pgvector_available(db):
        return []

    embedding_batch = await embed_texts([query])
    if not embedding_batch.embeddings:
        return []

    filter_sql, params = _semantic_filter_sql(filters)
    candidate_limit = max(limit * POSTGRES_SEMANTIC_CANDIDATE_MULTIPLIER, limit)
    result = await db.execute(
        text(
            f"""
            WITH ranked_chunks AS (
                SELECT
                    ka.id AS article_id,
                    kc.id AS chunk_id,
                    kc.content AS chunk_content,
                    1 - (kc.embedding <=> CAST(:embedding AS vector)) AS semantic_score,
                    row_number() OVER (
                        PARTITION BY ka.id
                        ORDER BY 1 - (kc.embedding <=> CAST(:embedding AS vector)) DESC, kc.id ASC
                    ) AS rank
                FROM knowledge_chunks kc
                JOIN knowledge_articles ka ON ka.id = kc.article_id
                WHERE ka.is_active IS TRUE
                  AND kc.is_active IS TRUE
                  AND kc.embedding IS NOT NULL
                  {filter_sql}
            )
            SELECT
                article_id,
                chunk_id,
                chunk_content,
                semantic_score
            FROM ranked_chunks
            WHERE rank = 1
            ORDER BY semantic_score DESC, article_id ASC
            LIMIT :candidate_limit
            """
        ),
        {
            **params,
            "embedding": vector_literal(embedding_batch.embeddings[0]),
            "candidate_limit": candidate_limit,
        },
    )
    scored_chunks = {
        int(article_id): {
            "chunk_id": int(chunk_id),
            "content": str(chunk_content or ""),
            "score": float(score or 0.0),
        }
        for article_id, chunk_id, chunk_content, score in result.all()
        if score is not None
    }
    if not scored_chunks:
        return []

    articles_result = await db.execute(
        select(KnowledgeArticle)
        .where(KnowledgeArticle.id.in_(scored_chunks.keys()))
        .order_by(KnowledgeArticle.id.asc())
    )
    now = datetime.now(UTC)
    medium_threshold = get_settings().RAG_SCORE_MEDIUM_THRESHOLD
    matches: list[KnowledgeMatch] = []
    for article in articles_result.scalars().all():
        chunk = scored_chunks[article.id]
        score = _score_article(
            query,
            query_tokens,
            article,
            filters,
            now,
            text_score=float(chunk["score"]) * POSTGRES_SEMANTIC_SCORE_WEIGHT,
        )
        alignment = _system_alignment(query, article)
        if alignment.reject:
            continue
        score += alignment.score_bonus
        if score >= medium_threshold:
            decision = _decision_for_score(score)
            if alignment.cap_to_clarify and decision == "answer":
                decision = "clarify"
            matches.append(
                KnowledgeMatch(
                    article=article,
                    score=score,
                    decision=decision,
                    snippet=_excerpt_from_text(str(chunk["content"]), query_tokens),
                    chunk_id=int(chunk["chunk_id"]),
                    retrieval="semantic",
                )
            )
    matches.sort(key=lambda match: (-match.score, match.article.id))
    return matches[:limit]


async def _search_knowledge_articles_hybrid_postgres(
    db: AsyncSession,
    query: str,
    query_tokens: set[str],
    limit: int,
    filters: KnowledgeSearchFilters,
) -> list[KnowledgeMatch]:
    fts_matches = await _search_knowledge_articles_postgres(
        db,
        query,
        query_tokens,
        limit,
        filters,
    )
    try:
        semantic_matches = await _search_knowledge_articles_semantic_postgres(
            db,
            query,
            query_tokens,
            limit,
            filters,
        )
    except Exception:
        semantic_matches = []
    return _merge_matches(fts_matches, semantic_matches, limit)


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
        datetime.now(UTC),
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

    # ── Cache lookup ──────────────────────────────────────────────────────
    # Кэш ловит повторные одинаковые запросы (типовые "не работает X" в
    # рабочие часы). Импорт ленивый — knowledge_cache.py типизирует через
    # TYPE_CHECKING и без него получим circular import.
    from app.services.knowledge_cache import get_knowledge_cache

    cache = get_knowledge_cache()
    cached = cache.get(query, limit, filters)
    if cached is not None:
        cached = [replace(match, article=await db.merge(match.article)) for match in cached]
        logger.debug(
            "Knowledge search cache hit",
            extra={"query_len": len(query), "limit": limit, "results": len(cached)},
        )
        return cached

    if _session_dialect_name(db) == "postgresql":
        matches = await _search_knowledge_articles_hybrid_postgres(
            db,
            query,
            query_tokens,
            limit,
            filters,
        )
        if len(matches) < limit:
            keyword_matches = await _search_knowledge_articles_fallback(
                db,
                query,
                query_tokens,
                limit,
                filters,
            )
            matches = _merge_matches(matches, keyword_matches, limit)
    else:
        matches = await _search_knowledge_articles_fallback(
            db,
            query,
            query_tokens,
            limit,
            filters,
        )

    cache.put(query, limit, filters, matches)
    return matches


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
        "chunk_id": match.chunk_id,
        "snippet": match.snippet,
        "retrieval": match.retrieval,
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


# Лимиты на построение KB-запроса. При длинных диалогах склейка всех
# user-сообщений вырастет до тысяч символов — FTS-токенайзер потащит мусор,
# а семантический эмбеддинг получит «среднее по больнице».
_KB_QUERY_MAX_USER_MESSAGES = 8
_KB_QUERY_MAX_CHARS = 2000
_ASSISTANT_KB_ANSWER_MARKERS = (
    "нашёл решение в базе знаний:",
    "нашел решение в базе знаний:",
    "похоже на статью базы знаний:",
    "если это не поможет",
)


def _assistant_messages_for_kb_query(assistant_messages: list[str]) -> list[str]:
    """Оставляет только короткие уточняющие вопросы ассистента для KB-query.

    Полные ответы из базы знаний нельзя возвращать обратно в retrieval:
    следующий пользовательский ответ вроде "не помогло" иначе будет искать
    по тексту уже выданной статьи и бот начнёт повторять одно и то же.
    """
    safe_messages: list[str] = []
    for message in assistant_messages:
        compact = _compact_text(message)
        lower = compact.casefold()
        if not compact:
            continue
        if any(marker in lower for marker in _ASSISTANT_KB_ANSWER_MARKERS):
            continue
        if len(compact) > 280:
            continue
        if "?" not in compact and "уточните" not in lower:
            continue
        safe_messages.append(compact)
    return safe_messages[-2:]


def _build_kb_query(user_messages: list[str], assistant_messages: list[str]) -> str:
    """Склеивает запрос к KB из истории диалога.

    Раньше брали только последние 3 user-сообщения. Проблема: бот часто
    задаёт уточняющие вопросы, и пользователь отвечает короткими репликами
    ("win10", "403", "vpn"). Главное описание проблемы оставалось в первом
    сообщении и выпадало из запроса → KB не находила релевантную статью.

    Стратегия:
      1) Самое свежее сообщение пользователя — главный источник intent
         (повторяем его дважды, чтобы поднять вес в FTS).
      2) Первое сообщение пользователя — обычно описание исходной проблемы.
      3) Промежуточные user-сообщения — короткие ответы на clarify-вопросы.
      4) Свежие уточняющие вопросы ассистента добавляем, потому что бот часто
         перефразирует проблему точнее ("вы имеете в виду VPN-туннель?").
         Полные KB-ответы ассистента не добавляем: они загрязняют следующий
         поиск и заставляют повторять ту же статью после "не помогло".

    После склейки обрезаем до _KB_QUERY_MAX_CHARS — слишком длинный
    запрос бесполезен для FTS (стоп-слова рассеиваются) и упирается в
    лимит контекста embedding-модели.
    """
    if not user_messages:
        return ""

    latest_user = user_messages[-1]
    parts: list[str] = [latest_user, latest_user]  # удвоение даёт +score в FTS

    if len(user_messages) >= 2:
        parts.append(user_messages[0])  # исходное описание проблемы

    # Промежуточные user-сообщения (без первого/последнего) — берём
    # последние из середины, ограничиваем количество.
    middle = user_messages[1:-1] if len(user_messages) >= 3 else []
    parts.extend(middle[-(_KB_QUERY_MAX_USER_MESSAGES - 3) :])

    # Последние короткие уточнения бота — там часто перефразирована проблема.
    parts.extend(_assistant_messages_for_kb_query(assistant_messages))

    query = "\n".join(part for part in parts if part)
    if len(query) > _KB_QUERY_MAX_CHARS:
        # Обрезаем по слову, чтобы не рвать токены посередине.
        truncated = query[:_KB_QUERY_MAX_CHARS]
        last_space = truncated.rfind(" ")
        if last_space > _KB_QUERY_MAX_CHARS // 2:
            truncated = truncated[:last_space]
        query = truncated
    return query


async def find_knowledge_answer(
    db: AsyncSession,
    messages: list[dict[str, str]],
    filters: KnowledgeSearchFilters | None = None,
    exclude_article_ids: set[int] | None = None,
) -> dict | None:
    """Ищет ответ в KB и возвращает payload с замеренной латенси поиска.

    Если match найден — payload[LATENCY_PAYLOAD_KEY] содержит миллисекунды,
    потраченные на search_knowledge_articles (включая FTS, semantic-поиск и
    hybrid-merge). Если нет — возвращаем None и не тратим бюджет на запись
    AILog: для intake-rules / прямого AI латенси замерят сами вызывающие.
    """
    user_messages = [
        message.get("content", "").strip()
        for message in messages
        if message.get("role") == "user" and message.get("content", "").strip()
    ]
    assistant_messages = [
        message.get("content", "").strip()
        for message in messages
        if message.get("role") == "assistant" and message.get("content", "").strip()
    ]
    if not user_messages:
        return None

    # LLM-rewrite запроса (feature-flag, default OFF). Если выключено
    # или вернулся None (таймаут/ошибка/не настроен) — fallback на
    # keyword-склейку из _build_kb_query.
    from app.services.ai_query_rewrite import rewrite_query_for_kb

    safe_assistant_messages = _assistant_messages_for_kb_query(assistant_messages)
    rewritten = await rewrite_query_for_kb(user_messages, safe_assistant_messages)
    query = rewritten or _build_kb_query(user_messages, safe_assistant_messages)
    if not query:
        return None

    started = time.perf_counter()
    search_limit = max(1, min(5, 1 + len(exclude_article_ids or set())))
    matches = await search_knowledge_articles(db, query, filters=filters, limit=search_limit)
    latency_ms = int((time.perf_counter() - started) * 1000)

    if exclude_article_ids:
        matches = [match for match in matches if match.article.id not in exclude_article_ids]
    if not matches:
        return None

    payload = build_knowledge_answer(matches[0], query)
    payload[LATENCY_PAYLOAD_KEY] = latency_ms
    logger.info(
        "Knowledge base answer matched",
        extra={
            "ai_latency_ms": latency_ms,
            "model_version": payload.get("model_version"),
            "ai_source": "kb",
            "knowledge_article_id": payload.get("knowledge_article_id"),
            "knowledge_score": payload.get("knowledge_score"),
        },
    )
    return payload
