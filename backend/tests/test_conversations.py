"""
Тесты роутера conversations: новый контракт с AI-Lead.

Что покрываем:
  1. POST /messages возвращает MessageRead с полями sources / ai_confidence /
     ai_escalate / requires_escalation.
  2. AI Service недоступен → fallback с requires_escalation=True
     (красная зона срабатывает автоматически).
  3. POST /escalate создаёт pre-filled тикет, переводит conversation
     в status="escalated", возвращает ticket + conversation_id.
  4. POST /escalate на чужой диалог → 404 (как и /tickets/{id} для чужого).
  5. POST /escalate на пустой диалог → 400.
  6. _load_history_for_ai мапит роли user/ai → user/assistant и берёт
     не больше MAX_HISTORY_MESSAGES.

В тестах AI Service реально не поднят, поэтому _get_ai_answer всегда
получает ConnectError и возвращает fallback. Этого достаточно, чтобы
проверить путь "AI недоступен → красная зона" — самый частый failure
mode в проде. Контракт с реально работающим AI проверяется отдельно
в integration-тестах AI-Lead (43 теста на стороне ai_module).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select


@pytest.fixture(autouse=True)
def _stub_ai_services(monkeypatch: pytest.MonkeyPatch):
    from app.services import ai_classifier, conversation_ai

    async def answer_fallback(conversation_id: int, messages: list[dict[str, str]]):
        return {
            "answer": "[AI Service временно недоступен. Ваше сообщение сохранено, агент ответит вручную.]",
            "confidence": 0.0,
            "escalate": True,
            "sources": [],
            "model_version": "test-fallback",
        }

    async def classify_fallback(ticket_id: int, title: str, body: str):
        inferred = ai_classifier._infer_priority_from_text(title, body)
        return {
            "category": "other",
            "department": "IT",
            "priority": ai_classifier._choose_priority("средний", inferred),
            "confidence": 0.0,
            "draft_response": "[AI Service недоступен — требует агента]",
            "model_version": "test-fallback",
            "response_time_ms": 0,
        }

    monkeypatch.setattr(conversation_ai, "get_ai_answer", answer_fallback)
    monkeypatch.setattr(ai_classifier, "classify_ticket", classify_fallback)


@pytest.fixture(autouse=True)
def _stub_ai_services(monkeypatch: pytest.MonkeyPatch):
    from app.services import ai_classifier, conversation_ai

    async def answer_fallback(conversation_id: int, messages: list[dict[str, str]]):
        return {
            "answer": "[AI Service временно недоступен. Ваше сообщение сохранено, агент ответит вручную.]",
            "confidence": 0.0,
            "escalate": True,
            "sources": [],
            "model_version": "test-fallback",
        }

    async def classify_fallback(ticket_id: int, title: str, body: str):
        inferred = ai_classifier._infer_priority_from_text(title, body)
        return {
            "category": "other",
            "department": "IT",
            "priority": ai_classifier._choose_priority("средний", inferred),
            "confidence": 0.0,
            "draft_response": "[AI Service недоступен — требует агента]",
            "model_version": "test-fallback",
            "response_time_ms": 0,
        }

    monkeypatch.setattr(conversation_ai, "get_ai_answer", answer_fallback)
    monkeypatch.setattr(ai_classifier, "classify_ticket", classify_fallback)


async def register_user(client: AsyncClient, suffix: str) -> tuple[int, str]:
    """Регистрирует пользователя и возвращает (id, access_token)."""
    response = await client.post("/api/v1/auth/register", json={
        "email": f"convuser{suffix}@example.com",
        "username": f"convuser{suffix}",
        "password": "Secret123!",
    })
    assert response.status_code == 201
    token = response.json()["access_token"]

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    return me.json()["id"], token


def escalation_payload(
    requester_name: str = "Иван Петров",
    requester_email: str = "ivan.petrov@example.com",
    office: str = "Главный офис",
    affected_item: str = "VPN",
) -> dict:
    return {
        "context": {
            "requester_name": requester_name,
            "requester_email": requester_email,
            "office": office,
            "affected_item": affected_item,
        },
    }


async def process_next_ai_job(db_session):
    from app.services.ai_jobs import claim_next_ai_job, process_ai_job

    job = await claim_next_ai_job(db_session)
    assert job is not None
    await process_ai_job(db_session, job)


@pytest.mark.asyncio
async def test_post_message_uses_knowledge_base_before_external_ai(
    client: AsyncClient,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.models.ai_log import AILog
    from app.models.knowledge_article import KnowledgeArticle
    from app.services import conversation_ai

    async def fail_if_called(conversation_id: int, messages: list[dict[str, str]]):
        raise AssertionError("External AI must not be called when knowledge base matches")

    monkeypatch.setattr(conversation_ai, "get_ai_answer", fail_if_called)
    db_session.add(
        KnowledgeArticle(
            department="IT",
            request_type="VPN не работает",
            title="VPN не подключается",
            body="Проверьте интернет, корпоративный профиль и MFA-код.",
            keywords="vpn впн удаленный доступ подключение",
            is_active=True,
        )
    )
    await db_session.flush()

    _, token = await register_user(client, "kbanswer")
    headers = {"Authorization": f"Bearer {token}"}
    conv_id = (await client.post("/api/v1/conversations/", headers=headers)).json()["id"]
    response = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "VPN не подключается, что проверить?"},
        headers=headers,
    )
    assert response.status_code == 201

    await process_next_ai_job(db_session)

    history = await client.get(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=headers,
    )
    assert history.status_code == 200
    ai_msg = history.json()[-1]
    assert ai_msg["requires_escalation"] is False
    assert ai_msg["ai_escalate"] is False
    assert ai_msg["sources"][0]["title"] == "VPN не подключается"
    assert ai_msg["sources"][0]["decision"] == "answer"
    assert "Проверьте интернет" in ai_msg["content"]

    result = await db_session.execute(
        select(AILog).where(AILog.conversation_id == conv_id)
    )
    log = result.scalar_one()
    assert log.outcome == "resolved_by_ai"
    assert log.model_version == "knowledge-base-v1"


# ── POST /messages: AI fallback должен дать requires_escalation=True ─────────

@pytest.mark.asyncio
async def test_post_message_ai_unavailable_marks_red_zone(client: AsyncClient, db_session):
    """
    AI Service в тестах недоступен → fallback в _get_ai_answer возвращает
    confidence=0.0 + escalate=True. Это ниже RED_ZONE_THRESHOLD=0.6, поэтому
    requires_escalation должен быть True — клиент по нему покажет кнопку
    "Создать тикет" вместо обычного ответа.
    """
    _, token = await register_user(client, "redzone")
    headers = {"Authorization": f"Bearer {token}"}

    # Создаём диалог
    conv_resp = await client.post("/api/v1/conversations/", headers=headers)
    assert conv_resp.status_code == 201
    conversation = conv_resp.json()
    assert conversation["created_at"]
    assert "updated_at" in conversation
    conv_id = conversation["id"]

    # Шлём сообщение
    msg_resp = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "Не могу войти в SAP, ошибка 403"},
        headers=headers,
    )
    assert msg_resp.status_code == 201

    # HTTP-запрос больше не ждёт модель: сразу возвращается только user message.
    messages = msg_resp.json()
    assert len(messages) == 1
    await process_next_ai_job(db_session)

    history_resp = await client.get(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=headers,
    )
    assert history_resp.status_code == 200
    messages = history_resp.json()
    assert len(messages) == 2
    user_msg, ai_msg = messages

    assert user_msg["role"] == "user"
    assert user_msg["content"] == "Не могу войти в SAP, ошибка 403"
    # У user-сообщения AI-метаданных нет
    assert user_msg["ai_confidence"] is None
    assert user_msg["sources"] is None
    assert user_msg["requires_escalation"] is None

    # У AI-сообщения есть полный набор метаданных
    assert ai_msg["role"] == "ai"
    assert ai_msg["ai_confidence"] == 0.0          # fallback
    assert ai_msg["ai_escalate"] is True           # fallback
    # Пустой список источников → пишем None в БД (чище, чем [], отличает
    # "источников нет" от "AI не отдавал поле sources вообще"). См.
    # `sources=ai_payload.get("sources") or None` в conversations.py.
    assert ai_msg["sources"] is None
    # Главное: красная зона сработала
    assert ai_msg["requires_escalation"] is True


# ── POST /messages: история сохраняется в правильном порядке ────────────────

@pytest.mark.asyncio
async def test_messages_persisted_in_chronological_order(client: AsyncClient, db_session):
    """Несколько сообщений подряд → GET /messages возвращает их по порядку."""
    _, token = await register_user(client, "history")
    headers = {"Authorization": f"Bearer {token}"}

    conv_id = (await client.post("/api/v1/conversations/", headers=headers)).json()["id"]

    for text in ("первое", "второе", "третье"):
        response = await client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={"content": text},
            headers=headers,
        )
        assert response.status_code == 201
        await process_next_ai_job(db_session)

    resp = await client.get(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=headers,
    )
    assert resp.status_code == 200
    messages = resp.json()

    # 3 пользовательских + 3 AI = 6
    assert len(messages) == 6
    user_contents = [m["content"] for m in messages if m["role"] == "user"]
    assert user_contents == ["первое", "второе", "третье"]


# ── POST /messages: чужой диалог → 404 ──────────────────────────────────────

@pytest.mark.asyncio
async def test_post_message_to_other_user_conversation_returns_404(client: AsyncClient):
    """Bob не может писать в диалог Alice → 404 (не палим существование)."""
    _, alice_token = await register_user(client, "ownerA")
    _, bob_token = await register_user(client, "ownerB")

    conv_id = (await client.post(
        "/api/v1/conversations/",
        headers={"Authorization": f"Bearer {alice_token}"},
    )).json()["id"]

    resp = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "это не моё, но попробую"},
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_draft_intent_forces_escalation_card(
    client: AsyncClient,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
):
    """Даже уверенный AI-ответ не должен скрывать явный запрос на черновик."""
    from app.services import conversation_ai

    async def confident_answer(conversation_id: int, messages: list[dict[str, str]]):
        return {
            "answer": "Обратитесь в техническую поддержку.",
            "confidence": 0.95,
            "escalate": False,
            "sources": [],
            "model_version": "test",
        }

    monkeypatch.setattr(conversation_ai, "get_ai_answer", confident_answer)

    _, token = await register_user(client, "draftintent")
    headers = {"Authorization": f"Bearer {token}"}

    conv_id = (await client.post("/api/v1/conversations/", headers=headers)).json()["id"]
    first_resp = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "порвался провод, срочно"},
        headers=headers,
    )
    assert first_resp.status_code == 201
    await process_next_ai_job(db_session)

    first_history = await client.get(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=headers,
    )
    assert first_history.status_code == 200
    assert first_history.json()[-1]["requires_escalation"] is True

    second_resp = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "давай создадим черновик для запроса к тех поддержке"},
        headers=headers,
    )
    assert second_resp.status_code == 201
    await process_next_ai_job(db_session)

    second_history = await client.get(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=headers,
    )
    assert second_history.status_code == 200
    ai_msg = second_history.json()[-1]
    assert ai_msg["ai_confidence"] == 0.5
    assert ai_msg["ai_escalate"] is True
    assert ai_msg["requires_escalation"] is True
    assert "Соберу данные для черновика" in ai_msg["content"]


# ── POST /escalate: 1-click autofill создаёт тикет ──────────────────────────

@pytest.mark.asyncio
async def test_escalate_creates_prefilled_ticket(client: AsyncClient, db_session):
    """
    После пары сообщений в диалоге пользователь жмёт "Эскалировать":
      - создаётся Ticket с conversation_id, ticket_source="ai_generated",
        confirmed_by_user=False (пользователь ещё не подтвердил отправку),
        status="pending_user";
      - Conversation.status переходит в "escalated";
      - В ответе — TicketRead + conversation_id.
    """
    user_id, token = await register_user(client, "escalate")
    headers = {"Authorization": f"Bearer {token}"}

    # Заводим диалог с парой сообщений (AI fallback нам не мешает —
    # классификатор тоже даёт fallback в тестах).
    conv_id = (await client.post("/api/v1/conversations/", headers=headers)).json()["id"]
    message_resp = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "Не работает VPN, я уже перезагружал ноут"},
        headers=headers,
    )
    assert message_resp.status_code == 201
    await process_next_ai_job(db_session)

    # 1-click эскалация
    resp = await client.post(
        f"/api/v1/conversations/{conv_id}/escalate",
        json={
            "context": {
                "requester_name": "Иван Петров",
                "requester_email": "ivan.petrov@example.com",
                "office": "Главный офис",
                "affected_item": "VPN",
            },
        },
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()

    assert body["conversation_id"] == conv_id
    ticket = body["ticket"]

    # Тикет принадлежит текущему пользователю и связан с диалогом
    assert ticket["user_id"] == user_id
    assert ticket["conversation_id"] == conv_id

    # Метаданные 1-click flow
    assert ticket["ticket_source"] == "ai_generated"
    assert ticket["confirmed_by_user"] is False
    assert ticket["status"] == "pending_user"

    # Title — первое сообщение пользователя (см. _extract → user_msgs[0])
    assert ticket["title"] == "Не работает VPN, я уже перезагружал ноут"

    # Body — сборка истории "Пользователь: ... \n\n AI: ..."
    assert "Контекст обращения:" in ticket["body"]
    assert "Автор: Иван Петров <ivan.petrov@example.com>" in ticket["body"]
    assert "Создал: convuserescalate <convuserescalate@example.com>" in ticket["body"]
    assert "Офис: Главный офис" in ticket["body"]
    assert "Объект: VPN" in ticket["body"]
    assert "Пользователь:" in ticket["body"]
    assert "AI:" in ticket["body"]
    assert ticket["requester_name"] == "Иван Петров"
    assert ticket["requester_email"] == "ivan.petrov@example.com"
    assert ticket["office"] == "Главный офис"
    assert ticket["affected_item"] == "VPN"

    # steps_tried должен подхватить "перезагружал" — наша эвристика
    assert ticket["steps_tried"] is not None
    assert "перезагружал" in ticket["steps_tried"]

    # Department принят из AI fallback (классификатор без AI отдаёт
    # валидный department="IT")
    assert ticket["department"] in {"IT", "HR", "finance"}
    assert ticket["ai_priority"] == "высокий"

    # Conversation теперь escalated
    conv_resp = await client.get("/api/v1/conversations/", headers=headers)
    convs = {c["id"]: c for c in conv_resp.json()}
    assert convs[conv_id]["status"] == "escalated"


@pytest.mark.asyncio
async def test_escalate_blank_requester_name_returns_422(
    client: AsyncClient,
    db_session,
):
    _, token = await register_user(client, "blankrequester")
    headers = {"Authorization": f"Bearer {token}"}

    conv_id = (await client.post("/api/v1/conversations/", headers=headers)).json()["id"]
    message_resp = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "Не работает VPN"},
        headers=headers,
    )
    assert message_resp.status_code == 201
    await process_next_ai_job(db_session)

    resp = await client.post(
        f"/api/v1/conversations/{conv_id}/escalate",
        json={
            "context": {
                "requester_name": "   ",
                "requester_email": "blank.requester@example.com",
                "office": "Главный офис",
                "affected_item": "VPN",
            },
        },
        headers=headers,
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_escalate_without_context_returns_422(client: AsyncClient, db_session):
    _, token = await register_user(client, "nocontext")
    headers = {"Authorization": f"Bearer {token}"}

    conv_id = (await client.post("/api/v1/conversations/", headers=headers)).json()["id"]
    message_resp = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "Не работает VPN"},
        headers=headers,
    )
    assert message_resp.status_code == 201
    await process_next_ai_job(db_session)

    resp = await client.post(
        f"/api/v1/conversations/{conv_id}/escalate",
        headers=headers,
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_message_to_escalated_conversation_returns_409(
    client: AsyncClient,
    db_session,
):
    _, token = await register_user(client, "lockedafterescalate")
    headers = {"Authorization": f"Bearer {token}"}

    conv_id = (await client.post("/api/v1/conversations/", headers=headers)).json()["id"]
    message_resp = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "Не работает VPN"},
        headers=headers,
    )
    assert message_resp.status_code == 201
    await process_next_ai_job(db_session)
    escalate_resp = await client.post(
        f"/api/v1/conversations/{conv_id}/escalate",
        json=escalation_payload(),
        headers=headers,
    )
    assert escalate_resp.status_code == 201

    message_resp = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "Еще важная деталь для агента"},
        headers=headers,
    )

    assert message_resp.status_code == 409


@pytest.mark.asyncio
async def test_repeated_escalate_returns_409(client: AsyncClient, db_session):
    _, token = await register_user(client, "doubleescalate")
    headers = {"Authorization": f"Bearer {token}"}

    conv_id = (await client.post("/api/v1/conversations/", headers=headers)).json()["id"]
    message_resp = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "Не работает VPN"},
        headers=headers,
    )
    assert message_resp.status_code == 201
    await process_next_ai_job(db_session)
    first_resp = await client.post(
        f"/api/v1/conversations/{conv_id}/escalate",
        json=escalation_payload(),
        headers=headers,
    )
    assert first_resp.status_code == 201

    second_resp = await client.post(
        f"/api/v1/conversations/{conv_id}/escalate",
        json=escalation_payload(),
        headers=headers,
    )
    assert second_resp.status_code == 409


@pytest.mark.asyncio
async def test_escalate_software_update_request_gets_low_priority(client: AsyncClient, db_session):
    """AI fallback text must not make routine how-to requests high priority."""
    _, token = await register_user(client, "updatevscode")
    headers = {"Authorization": f"Bearer {token}"}

    conv_id = (await client.post("/api/v1/conversations/", headers=headers)).json()["id"]
    message_resp = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "я хочу обновить программу VS Code, как это сделать?"},
        headers=headers,
    )
    assert message_resp.status_code == 201
    await process_next_ai_job(db_session)

    resp = await client.post(
        f"/api/v1/conversations/{conv_id}/escalate",
        json=escalation_payload(affected_item="VS Code"),
        headers=headers,
    )

    assert resp.status_code == 201
    assert resp.json()["ticket"]["ai_priority"] == "низкий"


# ── POST /escalate: пустой диалог → 400 ─────────────────────────────────────

@pytest.mark.asyncio
async def test_escalate_empty_conversation_returns_400(client: AsyncClient):
    """В диалоге нет ни одного сообщения → нечего классифицировать → 400."""
    _, token = await register_user(client, "emptyconv")
    headers = {"Authorization": f"Bearer {token}"}

    conv_id = (await client.post("/api/v1/conversations/", headers=headers)).json()["id"]

    resp = await client.post(
        f"/api/v1/conversations/{conv_id}/escalate",
        json=escalation_payload(),
        headers=headers,
    )
    assert resp.status_code == 400


# ── POST /escalate: чужой диалог → 404 ──────────────────────────────────────

@pytest.mark.asyncio
async def test_escalate_other_user_conversation_returns_404(client: AsyncClient, db_session):
    """Bob не может эскалировать диалог Alice → 404, не 403."""
    _, alice_token = await register_user(client, "escA")
    _, bob_token = await register_user(client, "escB")

    conv_id = (await client.post(
        "/api/v1/conversations/",
        headers={"Authorization": f"Bearer {alice_token}"},
    )).json()["id"]

    # Alice пишет сообщение, чтобы диалог был непустым
    message_resp = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "что-то приватное"},
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert message_resp.status_code == 201
    await process_next_ai_job(db_session)

    # Bob пытается эскалировать
    resp = await client.post(
        f"/api/v1/conversations/{conv_id}/escalate",
        json=escalation_payload(),
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert resp.status_code == 404


# ── _load_history_for_ai: маппинг ролей и ограничение по длине ──────────────

@pytest.mark.asyncio
async def test_load_history_maps_roles_and_limits_length(db_session, client: AsyncClient):
    """
    Прямой тест внутреннего хелпера:
      - role="ai" → "assistant" (стандарт OpenAI/Ollama, AI-Lead его ждёт);
      - role="user" остаётся "user";
      - не более MAX_HISTORY_MESSAGES возвращается;
      - порядок — хронологический (старое первым).
    """
    from app.models.conversation import Conversation
    from app.models.message import Message
    from app.models.user import User
    from app.services.conversation_ai import (
        MAX_HISTORY_MESSAGES,
        load_history_for_ai,
    )

    # Создаём в БД пользователя + диалог напрямую (минуя HTTP)
    user = User(
        email="hist@example.com",
        username="histuser",
        hashed_password="x",
        role="user",
    )
    db_session.add(user)
    await db_session.flush()

    conv = Conversation(user_id=user.id, status="active")
    db_session.add(conv)
    await db_session.flush()

    # Создаём MAX_HISTORY_MESSAGES + 5 сообщений, чередуя роли
    total = MAX_HISTORY_MESSAGES + 5
    for i in range(total):
        role = "user" if i % 2 == 0 else "ai"
        db_session.add(Message(
            conversation_id=conv.id,
            role=role,
            content=f"msg-{i}",
        ))
    await db_session.flush()

    history = await load_history_for_ai(db_session, conv.id)

    # Лимит
    assert len(history) == MAX_HISTORY_MESSAGES

    # Все роли — только user/assistant (никакого "ai")
    assert {h["role"] for h in history} <= {"user", "assistant"}

    # Хронологический порядок: последний элемент — самое свежее сообщение
    assert history[-1]["content"] == f"msg-{total - 1}"
    # Первый элемент — это сообщение с индексом (total - MAX_HISTORY_MESSAGES)
    assert history[0]["content"] == f"msg-{total - MAX_HISTORY_MESSAGES}"


# ── _extract_steps_tried: эвристика по ключевым словам ──────────────────────

def test_extract_steps_tried_finds_attempts():
    """Если пользователь упомянул "пробовал/перезагружал" — забираем строку."""
    from app.models.message import Message
    from app.routers.conversations import _extract_steps_tried

    msgs = [
        Message(role="user", content="Не работает SAP"),
        Message(role="ai", content="Что вы пробовали? Я должен знать. Пробовал помочь."),
        Message(role="user", content="Я перезагружал ноут и проверял VPN"),
        Message(role="user", content="Ничего особенного"),
    ]

    result = _extract_steps_tried(msgs)
    assert result is not None
    # AI-сообщение про "пробовал помочь" не должно попасть — фильтруем по role
    assert "пробовал помочь" not in result
    # User-сообщение с "перезагружал" должно попасть
    assert "перезагружал ноут" in result


def test_extract_steps_tried_returns_none_when_nothing_found():
    """Никаких упоминаний попыток → None, не пустая строка."""
    from app.models.message import Message
    from app.routers.conversations import _extract_steps_tried

    msgs = [
        Message(role="user", content="Просто вопрос"),
        Message(role="user", content="Ничего особенного"),
    ]
    assert _extract_steps_tried(msgs) is None


def test_support_draft_detection_handles_draft_request_and_urgent_wire():
    from app.services.conversation_ai import should_offer_support_draft

    assert should_offer_support_draft([
        {"role": "user", "content": "порвался провод, срочно"},
    ])
    assert should_offer_support_draft([
        {"role": "user", "content": "порвался провод, срочно"},
        {"role": "assistant", "content": "Потребуется специалист."},
        {
            "role": "user",
            "content": "давай создадим черновик для запроса к тех поддержке",
        },
    ])
    assert not should_offer_support_draft([
        {"role": "user", "content": "как обновить VS Code?"},
    ])
