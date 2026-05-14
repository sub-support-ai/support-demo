"""Тесты псевдо-стриминга ai_stage на conversations.

Что проверяем:
  1. Поле ai_stage присутствует в GET /conversations/{id} (None в idle-состоянии).
  2. _set_ai_stage не падает при несуществующем conversation_id.
  3. ai_stage сбрасывается в None при ошибке AI-обработки (fail_ai_job).
  4. ConversationRead сериализует ai_stage корректно для всех допустимых значений.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.conversation_ai import _set_ai_stage

# ── Helpers ───────────────────────────────────────────────────────────────────


async def _register(client: AsyncClient, suffix: str) -> tuple[int, str]:
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"stage{suffix}@example.com",
            "username": f"stage{suffix}",
            "password": "Secret123!",
        },
    )
    assert r.status_code == 201
    token = r.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return me.json()["id"], token


async def _create_conversation(client: AsyncClient, token: str) -> int:
    r = await client.post(
        "/api/v1/conversations/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201
    return r.json()["id"]


async def _get_conversation(client: AsyncClient, token: str, conv_id: int) -> dict:
    """Возвращает conversation из списка по id."""
    r = await client.get(
        "/api/v1/conversations/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    convs = {c["id"]: c for c in r.json()}
    assert conv_id in convs, f"Диалог {conv_id} не найден в списке"
    return convs[conv_id]


# ── Тесты ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ai_stage_field_present_and_null_at_rest(client: AsyncClient):
    """ai_stage присутствует в ответе и равен null, пока нет активной обработки."""
    _, token = await _register(client, "as1")
    conv_id = await _create_conversation(client, token)

    data = await _get_conversation(client, token, conv_id)
    assert "ai_stage" in data, "Поле ai_stage должно быть в ConversationRead"
    assert data["ai_stage"] is None


@pytest.mark.asyncio
async def test_ai_stage_set_and_visible_via_api(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """ai_stage, установленный в сессии, немедленно виден через API.

    Примечание: _set_ai_stage создаёт отдельную сессию и коммитит,
    что позволяет видеть значение раньше основного flush'а worker'а.
    В тестах мы имитируем это поведение напрямую через db_session,
    чтобы не зависеть от незакоммиченного состояния тест-транзакции.
    """
    from app.models.conversation import Conversation as Conv

    _, token = await _register(client, "as2")
    conv_id = await _create_conversation(client, token)

    # Устанавливаем стадию напрямую в db_session — тот же путь, что и worker
    conv = await db_session.get(Conv, conv_id)
    assert conv is not None
    conv.ai_stage = "searching"
    await db_session.flush()

    data = await _get_conversation(client, token, conv_id)
    assert data["ai_stage"] == "searching"

    # Сбрасываем
    conv.ai_stage = None
    await db_session.flush()
    data2 = await _get_conversation(client, token, conv_id)
    assert data2["ai_stage"] is None


@pytest.mark.asyncio
async def test_set_ai_stage_all_valid_values(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Каждое допустимое значение ai_stage сохраняется и читается без ошибок."""
    from app.models.conversation import Conversation as Conv

    _, token = await _register(client, "as3")
    conv_id = await _create_conversation(client, token)
    conv = await db_session.get(Conv, conv_id)
    assert conv is not None

    for stage in ("thinking", "searching", "found_kb", "generating", None):
        conv.ai_stage = stage
        await db_session.flush()
        data = await _get_conversation(client, token, conv_id)
        assert data["ai_stage"] == stage, f"Ожидали stage={stage!r}"


@pytest.mark.asyncio
async def test_set_ai_stage_nonexistent_conversation_does_not_raise():
    """_set_ai_stage молча игнорирует несуществующий conversation_id.

    Стадия — декоративная UX-функция: ошибки здесь не должны ломать основной
    flow обработки тикета.
    """
    # Не должно поднять исключение
    await _set_ai_stage(999999, "thinking")
    await _set_ai_stage(999999, None)


@pytest.mark.asyncio
async def test_ai_stage_reset_on_job_failure(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """После провала AI-job ai_stage сбрасывается в None (через fail_ai_job)."""
    from app.models.ai_job import AIJob
    from app.services.ai_jobs import fail_ai_job

    # Создаём пользователя и диалог напрямую в БД
    _, token = await _register(client, "as5")
    conv_id = await _create_conversation(client, token)

    # Устанавливаем стадию вручную — имитируем, что worker уже начал работу
    await _set_ai_stage(conv_id, "generating")

    # Создаём AI-job для этого диалога
    job = AIJob(
        conversation_id=conv_id,
        status="running",
        attempts=3,
    )
    db_session.add(job)
    await db_session.flush()

    # Вызываем fail_ai_job — он должен сбросить ai_stage
    await fail_ai_job(db_session, job, "тест: принудительный сброс")
    await db_session.flush()

    data = await _get_conversation(client, token, conv_id)
    assert data["ai_stage"] is None, "ai_stage должен быть None после fail_ai_job"
