"""
Тесты для app/services/quality_signals.py.

Покрываем:
  - _decay_weight: математика exponential decay
  - compute_quality_grade: классификация good/risky/bad по weighted_neg_ratio
  - decay-эффект: старый negative feedback не должен дискредитировать статью
  - refresh_article_quality_grade: сохранение в БД + защита suppressed
  - propagate_negative_feedback_for_ticket: feedback по escalated_ticket_id
  - не перезаписываем уже оценённые feedback'и
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.knowledge_article import KnowledgeArticle, KnowledgeArticleFeedback
from app.models.ticket import Ticket
from app.models.user import User
from app.services.quality_signals import (
    MIN_FEEDBACK_FOR_BAD,
    MIN_FEEDBACK_FOR_GRADE,
    QUALITY_GRADE_WINDOW_DAYS,
    _decay_weight,
    compute_quality_grade,
    propagate_negative_feedback_for_ticket,
    refresh_all_article_quality_grades,
    refresh_article_quality_grade,
)

# ── Хелперы для фабрик ───────────────────────────────────────────────────────


async def _make_user(db: AsyncSession, suffix: str) -> User:
    user = User(
        email=f"qs{suffix}@example.com",
        username=f"qs{suffix}",
        hashed_password="x",
        role="user",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_article(db: AsyncSession, title: str = "Test article") -> KnowledgeArticle:
    article = KnowledgeArticle(
        title=title,
        body="...",
        is_active=True,
    )
    db.add(article)
    await db.flush()
    return article


async def _make_conversation(db: AsyncSession, user_id: int) -> Conversation:
    conv = Conversation(user_id=user_id, status="active")
    db.add(conv)
    await db.flush()
    return conv


async def _add_feedback(
    db: AsyncSession,
    *,
    article: KnowledgeArticle,
    user: User,
    conv: Conversation,
    feedback: str | None,
    days_ago: float = 0.0,
    escalated_ticket_id: int | None = None,
    score: float = 5.0,
) -> KnowledgeArticleFeedback:
    """Создаёт KnowledgeArticleFeedback с указанным возрастом."""
    fb = KnowledgeArticleFeedback(
        article_id=article.id,
        conversation_id=conv.id,
        user_id=user.id,
        message_id=None,
        escalated_ticket_id=escalated_ticket_id,
        query="test query",
        score=score,
        decision="answer",
        feedback=feedback,
        created_at=datetime.now(UTC) - timedelta(days=days_ago),
    )
    db.add(fb)
    await db.flush()
    return fb


# ── _decay_weight ────────────────────────────────────────────────────────────


def test_decay_weight_zero_age_returns_full_weight():
    assert _decay_weight(0.0) == pytest.approx(1.0)


def test_decay_weight_one_half_life_returns_half():
    assert _decay_weight(30.0) == pytest.approx(0.5)


def test_decay_weight_two_half_lives_returns_quarter():
    assert _decay_weight(60.0) == pytest.approx(0.25)


def test_decay_weight_negative_age_clamped_to_zero():
    """Защита от случайного отрицательного age (clock skew, тест-фикстуры)."""
    assert _decay_weight(-10.0) == pytest.approx(1.0)


# ── compute_quality_grade ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grade_empty_article_is_good(db_session: AsyncSession):
    """Статья без feedback'а → grade='good' (default доверия)."""
    article = await _make_article(db_session)
    result = await compute_quality_grade(article.id, db_session)
    assert result.grade == "good"
    assert result.feedback_count == 0


@pytest.mark.asyncio
async def test_grade_below_min_count_stays_good(db_session: AsyncSession):
    """Меньше MIN_FEEDBACK_FOR_GRADE сигналов — даже все негативные → good."""
    user = await _make_user(db_session, "min1")
    conv = await _make_conversation(db_session, user.id)
    article = await _make_article(db_session)

    # 2 not_helped (< MIN_FEEDBACK_FOR_GRADE=3) — недостаточно данных
    for _ in range(MIN_FEEDBACK_FOR_GRADE - 1):
        await _add_feedback(
            db_session, article=article, user=user, conv=conv, feedback="not_helped"
        )

    result = await compute_quality_grade(article.id, db_session)
    assert result.grade == "good"


@pytest.mark.asyncio
async def test_grade_all_helped_is_good(db_session: AsyncSession):
    user = await _make_user(db_session, "h1")
    conv = await _make_conversation(db_session, user.id)
    article = await _make_article(db_session)

    for _ in range(5):
        await _add_feedback(db_session, article=article, user=user, conv=conv, feedback="helped")

    result = await compute_quality_grade(article.id, db_session)
    assert result.grade == "good"


@pytest.mark.asyncio
async def test_grade_50_50_is_risky(db_session: AsyncSession):
    """Половина negative (ratio=0.5) → risky (>= 0.4 threshold)."""
    user = await _make_user(db_session, "r1")
    conv = await _make_conversation(db_session, user.id)
    article = await _make_article(db_session)

    for _ in range(3):
        await _add_feedback(db_session, article=article, user=user, conv=conv, feedback="helped")
    for _ in range(3):
        await _add_feedback(
            db_session, article=article, user=user, conv=conv, feedback="not_helped"
        )

    result = await compute_quality_grade(article.id, db_session)
    assert result.grade == "risky"


@pytest.mark.asyncio
async def test_grade_mostly_negative_with_enough_signals_is_bad(db_session: AsyncSession):
    """ratio>=0.7 + MIN_FEEDBACK_FOR_BAD событий → bad."""
    user = await _make_user(db_session, "b1")
    conv = await _make_conversation(db_session, user.id)
    article = await _make_article(db_session)

    # 1 helped + 6 not_helped = ratio 0.86 (>= 0.7), count=7 (>= 5)
    await _add_feedback(db_session, article=article, user=user, conv=conv, feedback="helped")
    for _ in range(6):
        await _add_feedback(
            db_session, article=article, user=user, conv=conv, feedback="not_helped"
        )

    result = await compute_quality_grade(article.id, db_session)
    assert result.grade == "bad"


@pytest.mark.asyncio
async def test_grade_high_neg_ratio_but_few_signals_only_risky(db_session: AsyncSession):
    """Даже 100% negative — но < MIN_FEEDBACK_FOR_BAD событий → risky, не bad.

    Защита от случайных fluke'ов: 3 not_helped не должны фатально заблочить
    статью, только показать предупреждение.
    """
    user = await _make_user(db_session, "rb1")
    conv = await _make_conversation(db_session, user.id)
    article = await _make_article(db_session)

    # 3 not_helped (= MIN_FEEDBACK_FOR_GRADE, но < MIN_FEEDBACK_FOR_BAD)
    for _ in range(MIN_FEEDBACK_FOR_GRADE):
        await _add_feedback(
            db_session, article=article, user=user, conv=conv, feedback="not_helped"
        )

    result = await compute_quality_grade(article.id, db_session)
    assert result.grade == "risky"
    assert result.feedback_count < MIN_FEEDBACK_FOR_BAD


@pytest.mark.asyncio
async def test_grade_decay_old_negative_doesnt_dominate(db_session: AsyncSession):
    """Старый not_helped (60+ дней) весит мало; свежие helped перебивают."""
    user = await _make_user(db_session, "d1")
    conv = await _make_conversation(db_session, user.id)
    article = await _make_article(db_session)

    # 5 not_helped 60 дней назад (вес ~0.25 каждый = 1.25 total)
    for _ in range(5):
        await _add_feedback(
            db_session,
            article=article,
            user=user,
            conv=conv,
            feedback="not_helped",
            days_ago=60.0,
        )
    # 5 helped сегодня (вес 1.0 каждый = 5.0 total)
    for _ in range(5):
        await _add_feedback(db_session, article=article, user=user, conv=conv, feedback="helped")

    result = await compute_quality_grade(article.id, db_session)
    # weighted_neg ≈ 1.25, weighted_pos ≈ 5.0 → ratio ≈ 0.2 < RISKY (0.4)
    assert result.grade == "good"
    assert result.weighted_negative < result.weighted_positive


@pytest.mark.asyncio
async def test_grade_window_cutoff_ignores_very_old(db_session: AsyncSession):
    """Feedback старше QUALITY_GRADE_WINDOW_DAYS полностью игнорируется."""
    user = await _make_user(db_session, "w1")
    conv = await _make_conversation(db_session, user.id)
    article = await _make_article(db_session)

    # 10 not_helped старше окна — должны быть отфильтрованы SQL'ом
    for _ in range(10):
        await _add_feedback(
            db_session,
            article=article,
            user=user,
            conv=conv,
            feedback="not_helped",
            days_ago=QUALITY_GRADE_WINDOW_DAYS + 5,
        )

    result = await compute_quality_grade(article.id, db_session)
    # Все вне окна → feedback_count=0 → good (мало данных)
    assert result.grade == "good"
    assert result.feedback_count == 0


# ── refresh_article_quality_grade ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_updates_db_and_timestamp(db_session: AsyncSession):
    article = await _make_article(db_session)
    user = await _make_user(db_session, "u1")
    conv = await _make_conversation(db_session, user.id)
    for _ in range(6):
        await _add_feedback(
            db_session, article=article, user=user, conv=conv, feedback="not_helped"
        )

    assert article.quality_grade == "good"
    assert article.quality_grade_updated_at is None

    grade = await refresh_article_quality_grade(article.id, db_session)

    await db_session.refresh(article)
    assert grade == "bad"
    assert article.quality_grade == "bad"
    assert article.quality_grade_updated_at is not None


@pytest.mark.asyncio
async def test_refresh_preserves_suppressed_manual_flag(db_session: AsyncSession):
    """suppressed — ручной флаг админа; автоматика его не меняет даже при good feedback'е."""
    article = await _make_article(db_session)
    article.quality_grade = "suppressed"
    await db_session.flush()

    user = await _make_user(db_session, "sup1")
    conv = await _make_conversation(db_session, user.id)
    # 10 helped — статья отлично работает, НО админ её подавил
    for _ in range(10):
        await _add_feedback(db_session, article=article, user=user, conv=conv, feedback="helped")

    grade = await refresh_article_quality_grade(article.id, db_session)

    await db_session.refresh(article)
    assert grade == "suppressed"
    assert article.quality_grade == "suppressed"
    # timestamp всё равно обновился — чтобы фоновая job не возвращалась
    assert article.quality_grade_updated_at is not None


@pytest.mark.asyncio
async def test_refresh_all_processes_only_stale(db_session: AsyncSession):
    """refresh_all обрабатывает только статьи с stale timestamp'ом."""
    stale = await _make_article(db_session, "stale")
    stale.quality_grade_updated_at = datetime.now(UTC) - timedelta(hours=1)

    fresh = await _make_article(db_session, "fresh")
    fresh.quality_grade_updated_at = datetime.now(UTC) - timedelta(seconds=10)

    await _make_article(db_session, "never")  # quality_grade_updated_at = None
    await db_session.flush()

    count = await refresh_all_article_quality_grades(db_session, stale_after_seconds=300)

    # stale (1h > 5min) и never (NULL) обработаны; fresh (10s < 5min) — нет
    assert count == 2


# ── propagate_negative_feedback_for_ticket ───────────────────────────────────


@pytest.mark.asyncio
async def test_propagate_marks_unrated_as_not_helped(db_session: AsyncSession):
    user = await _make_user(db_session, "p1")
    conv = await _make_conversation(db_session, user.id)
    article = await _make_article(db_session)

    # Создаём тикет
    ticket = Ticket(
        user_id=user.id,
        title="VPN broken",
        body="...",
        user_priority=3,
        department="IT",
        status="resolved",
        confirmed_by_user=True,
    )
    db_session.add(ticket)
    await db_session.flush()

    # 3 unrated feedback'а, связанных с этим тикетом через escalated_ticket_id
    for _ in range(3):
        await _add_feedback(
            db_session,
            article=article,
            user=user,
            conv=conv,
            feedback=None,
            escalated_ticket_id=ticket.id,
        )

    updated = await propagate_negative_feedback_for_ticket(
        ticket.id, db_session, reason="ticket_reopened"
    )

    assert updated == 3
    # Все feedback'и теперь помечены как not_helped
    from sqlalchemy import select

    rows = await db_session.execute(
        select(KnowledgeArticleFeedback.feedback).where(
            KnowledgeArticleFeedback.escalated_ticket_id == ticket.id
        )
    )
    assert all(row[0] == "not_helped" for row in rows)


@pytest.mark.asyncio
async def test_propagate_does_not_overwrite_explicit_feedback(db_session: AsyncSession):
    """User feedback ('helped') приоритетнее автоматического вывода."""
    user = await _make_user(db_session, "p2")
    conv = await _make_conversation(db_session, user.id)
    article = await _make_article(db_session)
    ticket = Ticket(
        user_id=user.id,
        title="x",
        body="x",
        user_priority=3,
        department="IT",
        status="resolved",
        confirmed_by_user=True,
    )
    db_session.add(ticket)
    await db_session.flush()

    # Один уже оценён как 'helped' — пользователь явно сказал, что помогло
    helped_fb = await _add_feedback(
        db_session,
        article=article,
        user=user,
        conv=conv,
        feedback="helped",
        escalated_ticket_id=ticket.id,
    )
    # Один unrated
    unrated_fb = await _add_feedback(
        db_session,
        article=article,
        user=user,
        conv=conv,
        feedback=None,
        escalated_ticket_id=ticket.id,
    )

    updated = await propagate_negative_feedback_for_ticket(ticket.id, db_session)

    assert updated == 1
    await db_session.refresh(helped_fb)
    await db_session.refresh(unrated_fb)
    assert helped_fb.feedback == "helped"  # НЕ перезаписан
    assert unrated_fb.feedback == "not_helped"  # перезаписан


@pytest.mark.asyncio
async def test_propagate_triggers_grade_recalc(db_session: AsyncSession):
    """После propagate grade статьи пересчитывается, не ждём фоновой job."""
    user = await _make_user(db_session, "p3")
    conv = await _make_conversation(db_session, user.id)
    article = await _make_article(db_session)
    ticket = Ticket(
        user_id=user.id,
        title="x",
        body="x",
        user_priority=3,
        department="IT",
        status="resolved",
        confirmed_by_user=True,
    )
    db_session.add(ticket)
    await db_session.flush()

    # 7 unrated feedback'ов — после propagate станут not_helped → grade=bad
    for _ in range(MIN_FEEDBACK_FOR_BAD + 2):
        await _add_feedback(
            db_session,
            article=article,
            user=user,
            conv=conv,
            feedback=None,
            escalated_ticket_id=ticket.id,
        )

    assert article.quality_grade == "good"

    await propagate_negative_feedback_for_ticket(ticket.id, db_session)

    await db_session.refresh(article)
    assert article.quality_grade == "bad"
    # not_helped_count тоже увеличился
    assert article.not_helped_count >= 1


@pytest.mark.asyncio
async def test_propagate_no_feedback_returns_zero(db_session: AsyncSession):
    """Тикет без связанных feedback'ов — propagate безопасно возвращает 0."""
    user = await _make_user(db_session, "p4")
    ticket = Ticket(
        user_id=user.id,
        title="orphan",
        body="...",
        user_priority=3,
        department="IT",
        status="resolved",
        confirmed_by_user=True,
    )
    db_session.add(ticket)
    await db_session.flush()

    updated = await propagate_negative_feedback_for_ticket(ticket.id, db_session)
    assert updated == 0


# ── E2E: HTTP endpoint триггерит propagation ─────────────────────────────────


async def _register_user(client, suffix: str) -> tuple[int, str]:
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"qe{suffix}@example.com",
            "username": f"qe{suffix}",
            "password": "Secret123!",
        },
    )
    assert r.status_code == 201
    token = r.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return me.json()["id"], token


@pytest.mark.asyncio
async def test_e2e_rate_endpoint_triggers_propagation(client, db_session: AsyncSession):
    """POST /tickets/{id}/rate с rating=1 → связанный KB feedback становится not_helped."""
    from app.models.ticket_rating import TicketRating  # noqa: F401

    user_id, token = await _register_user(client, "e2e_rate")

    # Создаём resolved тикет + связанный с ним unrated KB feedback
    ticket = Ticket(
        user_id=user_id,
        title="VPN problem",
        body="...",
        user_priority=3,
        department="IT",
        status="resolved",
        confirmed_by_user=True,
    )
    db_session.add(ticket)
    await db_session.flush()

    article = await _make_article(db_session, "VPN guide")
    conv = await _make_conversation(db_session, user_id)
    fb = await _add_feedback(
        db_session,
        article=article,
        user=await db_session.get(User, user_id),
        conv=conv,
        feedback=None,
        escalated_ticket_id=ticket.id,
    )
    await db_session.flush()

    # Пользователь ставит rating=1
    r = await client.post(
        f"/api/v1/tickets/{ticket.id}/rate",
        headers={"Authorization": f"Bearer {token}"},
        json={"rating": 1, "comment": "ужасно"},
    )
    assert r.status_code == 201, r.text

    # KB feedback должен стать not_helped, счётчик статьи увеличиться
    await db_session.refresh(fb)
    await db_session.refresh(article)
    assert fb.feedback == "not_helped"
    assert article.not_helped_count >= 1


@pytest.mark.asyncio
async def test_grade_bad_excludes_article_from_rag_search(db_session: AsyncSession):
    """Статья с grade='bad' не появляется в search_knowledge_articles.

    Это «сердце» механизма обучения: плохая статья перестаёт выдаваться
    пользователям. Тест проверяет всю цепочку: grade → SQL фильтр → выдача.
    """
    from app.services.knowledge_base import KnowledgeSearchFilters, search_knowledge_articles
    from app.services.knowledge_cache import get_knowledge_cache

    # Кеш search-результатов TTL=60s между тестами — чистим, чтобы не получить
    # закешированный ответ из соседнего теста с тем же query.
    get_knowledge_cache().clear()

    good = await _make_article(db_session, "ALPHA guide good")
    good.keywords = "alphakeyword уникальный токен"
    bad = await _make_article(db_session, "ALPHA guide bad")
    bad.keywords = "alphakeyword уникальный токен"
    bad.quality_grade = "bad"
    await db_session.flush()

    matches = await search_knowledge_articles(
        db_session,
        "alphakeyword",
        filters=KnowledgeSearchFilters(access_scopes=("public",)),
    )
    article_ids = {m.article.id for m in matches}
    assert good.id in article_ids
    assert bad.id not in article_ids


@pytest.mark.asyncio
async def test_grade_suppressed_excludes_article_from_rag_search(db_session: AsyncSession):
    """Suppressed (ручной флаг админа) тоже исключается."""
    from app.services.knowledge_base import KnowledgeSearchFilters, search_knowledge_articles
    from app.services.knowledge_cache import get_knowledge_cache

    get_knowledge_cache().clear()

    article = await _make_article(db_session, "BETA suppressed")
    article.keywords = "betakeyword уникальный"
    article.quality_grade = "suppressed"
    await db_session.flush()

    matches = await search_knowledge_articles(
        db_session,
        "betakeyword",
        filters=KnowledgeSearchFilters(access_scopes=("public",)),
    )
    assert article.id not in {m.article.id for m in matches}


@pytest.mark.asyncio
async def test_negative_kb_article_ids_for_conversation(db_session: AsyncSession):
    """negative_kb_article_ids_for_conversation возвращает только not_helped/not_relevant."""
    from app.services.conversation_ai import negative_kb_article_ids_for_conversation

    user = await _make_user(db_session, "neg1")
    conv = await _make_conversation(db_session, user.id)
    article_negative = await _make_article(db_session, "negative")
    article_positive = await _make_article(db_session, "positive")
    article_unrated = await _make_article(db_session, "unrated")

    await _add_feedback(
        db_session,
        article=article_negative,
        user=user,
        conv=conv,
        feedback="not_helped",
    )
    await _add_feedback(
        db_session,
        article=article_positive,
        user=user,
        conv=conv,
        feedback="helped",
    )
    await _add_feedback(
        db_session,
        article=article_unrated,
        user=user,
        conv=conv,
        feedback=None,
    )

    result = await negative_kb_article_ids_for_conversation(db_session, conv.id)
    assert article_negative.id in result
    assert article_positive.id not in result
    assert article_unrated.id not in result


@pytest.mark.asyncio
async def test_weighted_feedback_score_overrides_legacy_formula(db_session: AsyncSession):
    """_feedback_score читает weighted_feedback_score когда оно != 0."""
    from app.services.knowledge_base import _feedback_score

    article = await _make_article(db_session, "Test article")
    # Legacy счётчики говорят «плохо», но weighted_score говорит «хорошо» —
    # weighted имеет приоритет (свежие данные после refresh).
    article.helped_count = 0
    article.not_helped_count = 10
    article.weighted_feedback_score = 1.5
    await db_session.flush()

    score = _feedback_score(article)
    assert score == pytest.approx(1.5)


@pytest.mark.asyncio
async def test_e2e_high_rating_does_not_trigger_propagation(client, db_session: AsyncSession):
    """POST /tickets/{id}/rate с rating=5 → unrated KB feedback остаётся unrated."""
    user_id, token = await _register_user(client, "e2e_high")

    ticket = Ticket(
        user_id=user_id,
        title="VPN problem",
        body="...",
        user_priority=3,
        department="IT",
        status="resolved",
        confirmed_by_user=True,
    )
    db_session.add(ticket)
    await db_session.flush()

    article = await _make_article(db_session, "VPN guide 2")
    conv = await _make_conversation(db_session, user_id)
    fb = await _add_feedback(
        db_session,
        article=article,
        user=await db_session.get(User, user_id),
        conv=conv,
        feedback=None,
        escalated_ticket_id=ticket.id,
    )
    await db_session.flush()

    r = await client.post(
        f"/api/v1/tickets/{ticket.id}/rate",
        headers={"Authorization": f"Bearer {token}"},
        json={"rating": 5, "comment": "отлично"},
    )
    assert r.status_code == 201, r.text

    await db_session.refresh(fb)
    # High CSAT не trigger'ит propagation — KB feedback остался unrated
    assert fb.feedback is None
