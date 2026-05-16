"""
Quality signals: автоматическая оценка KB-статей и propagation негативного
feedback из тикетов в KB.

Концепция «обучения»:
  - Каждый явный сигнал (CSAT, KB feedback) и неявный (reopen, escalation)
    превращается в запись KnowledgeArticleFeedback с feedback='not_helped'
    на соответствующих статьях.
  - Свежий feedback весит больше старого через exponential decay
    (half-life 30 дней). Это даёт статье шанс "реабилитироваться" после
    исправления, и при этом старые провалы не блокируют её навсегда.
  - Статьи классифицируются на 4 grade'а: good / risky / bad / suppressed.
    Эффекты в системе:
       good       — нейтрально, обычное ранжирование
       risky      — штраф к score в RAG-поиске, LLM получает hint о mixed feedback
       bad        — полностью исключается из RAG-выдачи
       suppressed — то же что bad, плюс ручной флаг "не возвращать пока админ
                    не разберётся" (автоматика этот grade не меняет)

Пороги выбраны консервативно: чтобы статья получила 'bad', нужно минимум
5 feedback событий И negative_ratio >= 0.7 (взвешенный). Это защищает от
случайных или малочисленных сигналов.

Где вызывается:
  - refresh_article_quality_grade — фоновой job'ой раз в N минут
  - propagate_negative_feedback_for_ticket — из ticket lifecycle (reopen,
    низкий CSAT, эскалация AI-диалога в тикет)
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_article import KnowledgeArticle, KnowledgeArticleFeedback

logger = logging.getLogger(__name__)


# ── Параметры decay и классификации ─────────────────────────────────────────

# Half-life feedback'а: через 30 дней вес снижается вдвое.
# 30 дней — баланс между «забываем быстро» (статью исправили — даём шанс)
# и «забываем медленно» (одиночный недавний not_helped не должен сразу
# дискредитировать долго работающую статью).
FEEDBACK_DECAY_HALF_LIFE_DAYS = 30.0

# Окно агрегации: feedback старше 90 дней игнорируется полностью (вес < 0.125).
QUALITY_GRADE_WINDOW_DAYS = 90

# Минимум событий для классификации. Меньше — статья считается 'good'
# независимо от ratio (мало данных = доверяем по умолчанию).
MIN_FEEDBACK_FOR_GRADE = 3
MIN_FEEDBACK_FOR_BAD = 5

# Пороги взвешенного negative_ratio.
RISKY_NEGATIVE_RATIO = 0.4
BAD_NEGATIVE_RATIO = 0.7

# Дефолтный TTL для grade в `refresh_all_article_quality_grades`. Пересчитываем
# статью не чаще, чем раз в 5 минут — даже если фоновая job побежит чаще.
DEFAULT_STALE_AFTER_SECONDS = 300


# ── Структуры ───────────────────────────────────────────────────────────────


@dataclass
class QualityGradeResult:
    """Результат вычисления grade — для UI/тестов/логов."""

    grade: str
    weighted_positive: float
    weighted_negative: float
    feedback_count: int
    # Нормализованный score [-2.0..+2.0]: (pos - neg) / total * 2.
    # 0.0 если данных нет. Это материализованное значение пишется в
    # KnowledgeArticle.weighted_feedback_score и используется в RAG-ranking.
    weighted_score: float = 0.0


# ── Decay-вычисление веса ───────────────────────────────────────────────────


def _decay_weight(age_days: float, half_life: float = FEEDBACK_DECAY_HALF_LIFE_DAYS) -> float:
    """Exponential decay: weight = 2 ** (-age / half_life).

    Свойства:
      age=0    → 1.0   (только что появился — полный вес)
      age=30   → 0.5   (half-life)
      age=60   → 0.25
      age=90   → 0.125 (граница окна QUALITY_GRADE_WINDOW_DAYS)
      age=180  → 0.016 (за окном, не учитываем)

    Используем 2** вместо math.exp() ради читаемости: half-life явно ровно
    FEEDBACK_DECAY_HALF_LIFE_DAYS, а не λ из e^(-λt).
    """
    return float(2.0 ** (-max(0.0, age_days) / half_life))


# ── Вычисление grade ────────────────────────────────────────────────────────


async def compute_quality_grade(
    article_id: int,
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> QualityGradeResult:
    """Пересчитывает quality_grade для одной статьи на основе её feedback'а.

    НЕ обновляет статью — только возвращает результат. Caller (например,
    refresh_article_quality_grade) решает, нужно ли коммитить.

    Параметр `now` — для тестируемости; в проде всегда datetime.now(UTC).
    """
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=QUALITY_GRADE_WINDOW_DAYS)

    rows = await db.execute(
        select(
            KnowledgeArticleFeedback.feedback,
            KnowledgeArticleFeedback.created_at,
        ).where(
            KnowledgeArticleFeedback.article_id == article_id,
            KnowledgeArticleFeedback.created_at >= cutoff,
            KnowledgeArticleFeedback.feedback.is_not(None),
        )
    )
    feedbacks = list(rows.all())

    # Считаем weighted_pos/neg всегда, даже если ниже MIN_FEEDBACK_FOR_GRADE,
    # потому что weighted_score материализуется отдельно от grade и
    # используется в incremental ranking — даже 1 helped/not_helped полезен
    # как небольшой signal-bump.
    weighted_pos = 0.0
    weighted_neg = 0.0
    for fb_value, created_at in feedbacks:
        # БД может вернуть naive datetime в SQLite даже если столбец timezone-aware
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        age_days = (now - created_at).total_seconds() / 86400.0
        weight = _decay_weight(age_days)
        if fb_value == "helped":
            weighted_pos += weight
        elif fb_value in ("not_helped", "not_relevant"):
            weighted_neg += weight

    total_weighted = weighted_pos + weighted_neg

    if total_weighted == 0:
        # Нет валидных feedback'ов (или все за окном).
        return QualityGradeResult(
            grade="good",
            weighted_positive=0.0,
            weighted_negative=0.0,
            feedback_count=len(feedbacks),
            weighted_score=0.0,
        )

    # Нормализованный score в диапазоне [-2.0, +2.0] —
    # совместим со старой формулой (helped-neg)/total*2.
    weighted_score = max(-2.0, min(2.0, (weighted_pos - weighted_neg) / total_weighted * 2.0))

    if len(feedbacks) < MIN_FEEDBACK_FOR_GRADE:
        # Слишком мало данных для уверенного вердикта по grade.
        # Default 'good': лучше показать потенциально полезную статью,
        # чем заблочить её на основе 1-2 случайных not_helped.
        # weighted_score всё равно возвращаем — он даёт incremental signal.
        return QualityGradeResult(
            grade="good",
            weighted_positive=weighted_pos,
            weighted_negative=weighted_neg,
            feedback_count=len(feedbacks),
            weighted_score=weighted_score,
        )

    neg_ratio = weighted_neg / total_weighted

    # Bad: высокий negative_ratio + большой объём событий
    if neg_ratio >= BAD_NEGATIVE_RATIO and len(feedbacks) >= MIN_FEEDBACK_FOR_BAD:
        grade = "bad"
    elif neg_ratio >= RISKY_NEGATIVE_RATIO:
        grade = "risky"
    else:
        grade = "good"

    return QualityGradeResult(
        grade=grade,
        weighted_positive=weighted_pos,
        weighted_negative=weighted_neg,
        feedback_count=len(feedbacks),
        weighted_score=weighted_score,
    )


# ── Сохранение grade ────────────────────────────────────────────────────────


async def refresh_article_quality_grade(
    article_id: int,
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> str:
    """Пересчитывает grade и сохраняет в article. Возвращает финальный grade.

    Бизнес-правило: `suppressed` — ручной флаг (админ явно подавил статью).
    Автоматика его НЕ снимает — только админ. Мы только обновляем timestamp,
    чтобы фоновая job не возвращалась к этой статье до следующего цикла.
    """
    now = now or datetime.now(UTC)
    article = await db.get(KnowledgeArticle, article_id)
    if article is None:
        logger.warning("Попытка обновить grade несуществующей статьи %s", article_id)
        return "good"

    if article.quality_grade == "suppressed":
        article.quality_grade_updated_at = now
        await db.flush()
        return "suppressed"

    result = await compute_quality_grade(article_id, db, now=now)
    previous = article.quality_grade
    article.quality_grade = result.grade
    article.quality_grade_updated_at = now
    # Материализуем decay-взвешенный score — его читает _feedback_score
    # в knowledge_base.py при RAG-ranking.
    article.weighted_feedback_score = result.weighted_score
    await db.flush()

    if previous != result.grade:
        logger.info(
            "quality_grade изменён",
            extra={
                "article_id": article_id,
                "previous": previous,
                "new": result.grade,
                "weighted_negative": round(result.weighted_negative, 2),
                "weighted_positive": round(result.weighted_positive, 2),
                "feedback_count": result.feedback_count,
            },
        )
    return result.grade


async def refresh_all_article_quality_grades(
    db: AsyncSession,
    *,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
    now: datetime | None = None,
) -> int:
    """Фоновая job: пересчитывает grade для всех активных статей,
    которые давно не обновлялись (либо никогда).

    Возвращает количество обработанных статей.
    """
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(seconds=stale_after_seconds)

    rows = await db.execute(
        select(KnowledgeArticle.id).where(
            or_(
                KnowledgeArticle.quality_grade_updated_at.is_(None),
                KnowledgeArticle.quality_grade_updated_at < cutoff,
            ),
            KnowledgeArticle.is_active.is_(True),
        )
    )
    article_ids = [row[0] for row in rows]

    for aid in article_ids:
        await refresh_article_quality_grade(aid, db, now=now)

    if article_ids:
        logger.info("Пересчитано quality_grade для %d статей", len(article_ids))
    return len(article_ids)


# ── Propagation негативного feedback из тикетов ─────────────────────────────


async def propagate_negative_feedback_for_ticket(
    ticket_id: int,
    db: AsyncSession,
    *,
    reason: str = "ticket_reopened",
    now: datetime | None = None,
) -> int:
    """Когда тикет получает сильный негативный сигнал (reopen / низкий CSAT /
    эскалация AI→agent) — все KnowledgeArticleFeedback связанные с этим тикетом
    через `escalated_ticket_id` и не имеющие явного feedback'а ПОМЕЧАЮТСЯ
    как 'not_helped'. Это и есть «обучение»: система запоминает, что выданный
    AI-ответ не сработал.

    Уже оценённые feedback'и (helped/not_helped/not_relevant) НЕ перезаписываются —
    user feedback приоритетнее автоматического вывода.

    Returns: число обновлённых feedback-записей.
    """
    now = now or datetime.now(UTC)

    rows = await db.execute(
        select(KnowledgeArticleFeedback).where(
            KnowledgeArticleFeedback.escalated_ticket_id == ticket_id,
            KnowledgeArticleFeedback.feedback.is_(None),
        )
    )
    feedbacks = list(rows.scalars().all())

    if not feedbacks:
        return 0

    affected_article_ids: set[int] = set()
    for fb in feedbacks:
        fb.feedback = "not_helped"
        affected_article_ids.add(fb.article_id)

    # Инкрементим счётчик на статье — это сохраняет совместимость со
    # старыми местами кода, читающими not_helped_count напрямую.
    for aid in affected_article_ids:
        article = await db.get(KnowledgeArticle, aid)
        if article is not None:
            article.not_helped_count = (article.not_helped_count or 0) + 1

    await db.flush()

    # Сразу пересчитываем grade — не ждём фоновую job. Реакция на негативный
    # сигнал должна быть мгновенной, особенно если статья перешла в 'bad'.
    for aid in affected_article_ids:
        await refresh_article_quality_grade(aid, db, now=now)

    logger.info(
        "Propagated negative feedback из тикета",
        extra={
            "ticket_id": ticket_id,
            "reason": reason,
            "feedbacks_updated": len(feedbacks),
            "articles_affected": len(affected_article_ids),
        },
    )
    return len(feedbacks)
