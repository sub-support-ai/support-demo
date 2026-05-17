import importlib
import logging
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))


# В реальном `requests` HTTPError — подкласс RequestException, а Timeout —
# подкласс ConnectionError. Если в моке всё свести к плоскому Exception,
# первый `except requests.HTTPError` в коде сервиса будет ловить вообще
# любую ошибку, и тесты на 502 для обычной сетевой проблемы пройдут не там,
# где задумывались. Поэтому держим иерархию, как в настоящем requests.
class _MockRequestException(Exception):
    pass


class _MockHTTPError(_MockRequestException):
    pass


class _MockTimeout(_MockRequestException):
    pass


sys.modules.setdefault(
    "requests",
    types.SimpleNamespace(
        RequestException=_MockRequestException,
        HTTPError=_MockHTTPError,
        Timeout=_MockTimeout,
        post=lambda *_args, **_kwargs: None,
        get=lambda *_args, **_kwargs: None,
    ),
)

answerer = importlib.import_module("answerer")
classifier = importlib.import_module("classifier")
service_main = importlib.import_module("main")


class _FakeResponse:
    """Универсальный заглушка-ответ для requests.post / requests.get.

    Заменяет три типа ad-hoc моков, которые накопились в этом файле:
      - валидный ответ модели    → _FakeResponse({"message": {"content": "..."}})
      - сломанный JSON           → _FakeResponse({"message": {"content": "not json"}})
      - произвольный API-ответ   → _FakeResponse({"embeddings": [...]})
    """

    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise service_main.requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._payload


class _BrokenJsonResponse(_FakeResponse):
    """Сохранён для обратной совместимости со старыми тестами в этом файле."""

    def __init__(self) -> None:
        super().__init__({"message": {"content": "not json"}})


def test_answerer_returns_fallback_on_ollama_timeout(monkeypatch):
    def raise_timeout(*_args, **_kwargs):
        raise answerer.requests.Timeout("timeout")

    monkeypatch.setattr(answerer.requests, "post", raise_timeout)

    result = answerer.generate_answer(
        conversation_id=1,
        messages=[SimpleNamespace(role="user", content="vpn is down")],
    )

    assert result["confidence"] == 0.0
    assert result["escalate"] is True
    assert result["sources"] == []


def test_answerer_returns_fallback_on_invalid_model_json(monkeypatch):
    monkeypatch.setattr(
        answerer.requests,
        "post",
        lambda *_args, **_kwargs: _FakeResponse({"message": {"content": "not json"}}),
    )

    result = answerer.generate_answer(
        conversation_id=1,
        messages=[SimpleNamespace(role="user", content="vpn is down")],
    )

    assert result["confidence"] == 0.0
    assert result["escalate"] is True


def test_classifier_returns_safe_fallback_on_ollama_error(monkeypatch):
    def raise_timeout(*_args, **_kwargs):
        raise classifier.requests.Timeout("timeout")

    monkeypatch.setattr(classifier.requests, "post", raise_timeout)

    result = classifier.classify_ticket(
        ticket_id=None,
        title="VPN issue",
        body="VPN does not connect",
    )

    assert result["category"] == "other"
    assert result["department"] == "other"
    assert result["confidence"] == 0.0


# ── Блок 5: happy-path и edge-cases для answerer / classifier ───────────────


def test_answerer_parses_valid_response(monkeypatch):
    """Нормальный JSON от модели прокидывается в результат как есть.

    confidence=0.85 > 0.6 → escalate из ответа сохраняется, не форсится.
    """
    monkeypatch.setattr(
        answerer.requests,
        "post",
        lambda *_args, **_kwargs: _FakeResponse(
            {
                "message": {
                    "content": (
                        '{"answer": "Перезагрузите роутер.", '
                        '"confidence": 0.85, '
                        '"escalate": false, '
                        '"sources": []}'
                    )
                }
            }
        ),
    )

    result = answerer.generate_answer(
        conversation_id=1,
        messages=[SimpleNamespace(role="user", content="нет интернета")],
    )

    assert result["answer"] == "Перезагрузите роутер."
    assert result["confidence"] == 0.85
    assert result["escalate"] is False
    assert result["sources"] == []
    assert result["model_version"] == answerer.MODEL_VERSION


def test_answerer_low_confidence_forces_escalate(monkeypatch):
    """Если модель вернула confidence < 0.6 — escalate принудительно True,
    даже если сама модель сказала False.

    Регрессия: AI-сервис не должен молча отдавать неуверенный ответ — фронт
    обязан показать кнопку «Создать тикет», а это решается escalate=True.
    """
    monkeypatch.setattr(
        answerer.requests,
        "post",
        lambda *_args, **_kwargs: _FakeResponse(
            {
                "message": {
                    "content": (
                        '{"answer": "Я не уверен.", '
                        '"confidence": 0.3, '
                        '"escalate": false, '
                        '"sources": []}'
                    )
                }
            }
        ),
    )

    result = answerer.generate_answer(
        conversation_id=1,
        messages=[SimpleNamespace(role="user", content="странный вопрос")],
    )

    assert result["confidence"] == 0.3
    assert result["escalate"] is True


def test_answerer_uses_deterministic_security_response(monkeypatch):
    """Security-сценарии не отдаём на свободную генерацию модели.

    Модель может выдумать неизвестный термин. Для подозрительных писем,
    ссылок и компрометации учётной записи нужен стандартный безопасный текст.
    """

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Security answer must not call Ollama")

    monkeypatch.setattr(answerer.requests, "post", fail_if_called)

    result = answerer.generate_answer(
        conversation_id=1,
        messages=[
            SimpleNamespace(
                role="user",
                content="Мне пришло подозрительное письмо со ссылкой, просят пароль",
            )
        ],
    )

    assert result["escalate"] is True
    assert result["confidence"] == 0.95
    assert "фишинг" in result["answer"]
    assert "подозрительное письмо" in result["answer"]
    assert "вредоносной ссылке" in result["answer"]
    assert "компрометация учётной записи" in result["answer"]
    assert "шкерб" not in result["answer"].lower()


def test_answerer_strips_markdown_code_fence(monkeypatch):
    """Mistral любит обернуть JSON в ```json ... ``` — answerer должен это снять.

    Регрессия для случая, когда модель не послушалась «без markdown».
    """
    fenced = (
        "```json\n"
        '{"answer": "ok", "confidence": 0.9, "escalate": false, "sources": []}\n'
        "```"
    )
    monkeypatch.setattr(
        answerer.requests,
        "post",
        lambda *_args, **_kwargs: _FakeResponse({"message": {"content": fenced}}),
    )

    result = answerer.generate_answer(
        conversation_id=1,
        messages=[SimpleNamespace(role="user", content="что-нибудь")],
    )

    assert result["answer"] == "ok"
    assert result["confidence"] == 0.9


def test_classifier_parses_valid_response(monkeypatch):
    """Нормальный JSON от модели → category/department/priority берутся как есть."""
    monkeypatch.setattr(
        classifier.requests,
        "post",
        lambda *_args, **_kwargs: _FakeResponse(
            {
                "message": {
                    "content": (
                        '{"category": "it_access", '
                        '"priority": "высокий", '
                        '"confidence": 0.92, '
                        '"draft_response": "Проверьте пароль..."}'
                    )
                }
            }
        ),
    )

    result = classifier.classify_ticket(
        ticket_id=10,
        title="не могу зайти",
        body="забыл пароль",
    )

    assert result["category"] == "it_access"
    assert result["department"] == "IT"  # маппинг через CATEGORY_TO_DEPARTMENT
    assert result["priority"] == "высокий"
    assert result["confidence"] == 0.92
    assert "пароль" in result["draft_response"]


def test_classifier_clamps_unknown_category_to_other(monkeypatch):
    """Если модель выдумала категорию вне whitelist — приземляем на other.

    Эта защита поверх Pydantic-валидации в main.py: контракт на стороне
    клиента (backend) гарантирует, что приходит одна из заранее известных
    категорий.
    """
    monkeypatch.setattr(
        classifier.requests,
        "post",
        lambda *_args, **_kwargs: _FakeResponse(
            {
                "message": {
                    "content": (
                        '{"category": "it_quantum_blockchain", '
                        '"priority": "высокий", '
                        '"confidence": 0.8}'
                    )
                }
            }
        ),
    )

    result = classifier.classify_ticket(ticket_id=1, title="x", body="y")

    assert result["category"] == "other"
    assert result["department"] == "other"


def test_classifier_clamps_unknown_priority_to_medium(monkeypatch):
    """Приоритет вне whitelist → «средний» как разумный дефолт.

    Альтернатива «высокий» бы обрушила SLA-метрики ложными срочными тикетами.
    """
    monkeypatch.setattr(
        classifier.requests,
        "post",
        lambda *_args, **_kwargs: _FakeResponse(
            {
                "message": {
                    "content": (
                        '{"category": "it_access", '
                        '"priority": "ASAP", '
                        '"confidence": 0.8}'
                    )
                }
            }
        ),
    )

    result = classifier.classify_ticket(ticket_id=1, title="x", body="y")

    assert result["priority"] == "средний"


# ── Блок 5: /ai/embed endpoint ─────────────────────────────────────────────


def test_embeddings_endpoint_returns_vectors_on_success(monkeypatch):
    """Happy path: Ollama вернул новый формат /api/embed → вектора как есть."""
    monkeypatch.setattr(service_main, "AI_SERVICE_API_KEY", None)
    monkeypatch.setattr(
        service_main.requests,
        "post",
        lambda *_args, **_kwargs: _FakeResponse(
            {"embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]}
        ),
    )
    client = TestClient(service_main.app)

    response = client.post("/ai/embed", json={"texts": ["hello", "world"]})

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == service_main.OLLAMA_EMBED_MODEL
    assert body["embeddings"] == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]


def test_embeddings_endpoint_rejects_only_whitespace_input(monkeypatch):
    """Все строки — пустые/пробелы → 422 (нечего эмбеддить).

    Pydantic пропустит min_length=1 (одна непустая строка), но дальнейший
    strip() оставит пустой список → endpoint вручную возвращает 422.
    """
    monkeypatch.setattr(service_main, "AI_SERVICE_API_KEY", None)
    client = TestClient(service_main.app)

    response = client.post("/ai/embed", json={"texts": ["   ", "\t"]})

    assert response.status_code == 422


def test_embeddings_endpoint_returns_502_on_ollama_failure(monkeypatch):
    """Ollama недоступен → 502, а не 500.

    502 семантически точнее: проблема не у нас, а у апстрима. Front-end
    умеет показывать 502 как «AI недоступен», на 500 покажет белую ошибку.
    """
    monkeypatch.setattr(service_main, "AI_SERVICE_API_KEY", None)

    def raise_connection(*_args, **_kwargs):
        raise service_main.requests.RequestException("connection refused")

    monkeypatch.setattr(service_main.requests, "post", raise_connection)
    client = TestClient(service_main.app)

    response = client.post("/ai/embed", json={"texts": ["hello"]})

    assert response.status_code == 502


def test_embeddings_endpoint_rejects_invalid_payload_shape(monkeypatch):
    """Если Ollama вернул payload без поля embeddings — отдаём 502.

    Это страховка от тихой смены контракта Ollama (или legacy /api/embeddings,
    который вернул что-то странное).
    """
    monkeypatch.setattr(service_main, "AI_SERVICE_API_KEY", None)
    monkeypatch.setattr(
        service_main.requests,
        "post",
        lambda *_args, **_kwargs: _FakeResponse({"unexpected": "shape"}),
    )
    client = TestClient(service_main.app)

    response = client.post("/ai/embed", json={"texts": ["hello"]})

    assert response.status_code == 502


# ── Блок 5: /healthcheck endpoint ──────────────────────────────────────────


def test_healthcheck_returns_ok_when_ollama_healthy(monkeypatch):
    """Healthcheck считает Ollama живым: и chat-, и embed-модель найдены в /api/tags."""
    monkeypatch.setattr(
        service_main.requests,
        "get",
        lambda *_args, **_kwargs: _FakeResponse(
            {
                "models": [
                    {"name": service_main.OLLAMA_MODEL},
                    {"name": service_main.OLLAMA_EMBED_MODEL},
                ]
            }
        ),
    )
    client = TestClient(service_main.app)

    response = client.get("/healthcheck")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["ollama"] == "ok"


def test_healthcheck_marks_degraded_when_ollama_unavailable(monkeypatch):
    """Ollama не отвечает → status=degraded, ollama=unavailable, причина в detail.

    Возвращаем 200 с degraded (а не 5xx) намеренно: оркестратор должен видеть
    factory-pod живым (HTTP-сервер работает), а deg signal — отдельным каналом.
    """
    def raise_connection(*_args, **_kwargs):
        raise service_main.requests.RequestException("connection refused")

    monkeypatch.setattr(service_main.requests, "get", raise_connection)
    client = TestClient(service_main.app)

    response = client.get("/healthcheck")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["ollama"] == "unavailable"
    assert "connection refused" in body["detail"]


def test_healthcheck_marks_degraded_when_chat_model_missing(monkeypatch):
    """Ollama жив, но нужная chat-модель не подгружена — это тоже degraded.

    Реальный кейс: после `docker compose up` админ забыл `ollama pull mistral`,
    и /api/tags возвращает только embed-модель. Healthcheck должен сигналить.
    """
    monkeypatch.setattr(
        service_main.requests,
        "get",
        lambda *_args, **_kwargs: _FakeResponse(
            {"models": [{"name": service_main.OLLAMA_EMBED_MODEL}]}
        ),
    )
    client = TestClient(service_main.app)

    response = client.get("/healthcheck")

    body = response.json()
    assert body["status"] == "degraded"
    assert body["detail"] == "model_not_found"


def test_healthcheck_marks_degraded_when_embed_model_missing(monkeypatch):
    """Симметрично: нет embed-модели → degraded с другим detail.

    Без embed-модели KB-семантический поиск возвращает 502; до запуска
    тестов это надо отлавливать на healthcheck-уровне, а не на первом /ai/embed.
    """
    monkeypatch.setattr(
        service_main.requests,
        "get",
        lambda *_args, **_kwargs: _FakeResponse(
            {"models": [{"name": service_main.OLLAMA_MODEL}]}
        ),
    )
    client = TestClient(service_main.app)

    response = client.get("/healthcheck")

    body = response.json()
    assert body["status"] == "degraded"
    assert body["detail"] == "embed_model_not_found"


def test_ai_service_rejects_requests_with_wrong_key(monkeypatch):
    monkeypatch.setattr(service_main, "AI_SERVICE_API_KEY", "secret")
    client = TestClient(service_main.app)

    response = client.post(
        "/ai/answer",
        headers={"X-AI-Service-Key": "wrong"},
        json={
            "conversation_id": 1,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 401


def test_ai_service_accepts_requests_with_configured_key(monkeypatch):
    monkeypatch.setattr(service_main, "AI_SERVICE_API_KEY", "secret")
    monkeypatch.setattr(
        service_main,
        "generate_answer",
        lambda conversation_id, messages: {
            "answer": "ok",
            "confidence": 0.9,
            "escalate": False,
            "sources": [],
            "model_version": "test",
        },
    )
    client = TestClient(service_main.app)

    response = client.post(
        "/ai/answer",
        headers={"X-AI-Service-Key": "secret"},
        json={
            "conversation_id": 1,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "ok"


# ── Fail-closed config: production обязан иметь AI_SERVICE_API_KEY ───────────


def test_validate_startup_config_raises_in_production_without_key(monkeypatch):
    """Без ключа сервис не должен стартовать в production.

    Регрессия: раньше require_api_key молча пропускал запросы при пустом
    AI_SERVICE_API_KEY — на production это означало открытый /ai/* для
    любого, кто достучался до :8001.
    """
    monkeypatch.setattr(service_main, "APP_ENV", "production")
    monkeypatch.setattr(service_main, "AI_SERVICE_API_KEY", None)

    with pytest.raises(RuntimeError, match="AI_SERVICE_API_KEY"):
        service_main._validate_startup_config()


def test_validate_startup_config_allows_production_when_key_set(monkeypatch):
    """Production с заданным ключом стартует без ошибок."""
    monkeypatch.setattr(service_main, "APP_ENV", "production")
    monkeypatch.setattr(service_main, "AI_SERVICE_API_KEY", "prod-secret")

    # Не должно бросать
    service_main._validate_startup_config()


def test_validate_startup_config_warns_in_development_without_key(
    monkeypatch, caplog
):
    """В dev без ключа сервис стартует, но один раз пишет WARNING."""
    monkeypatch.setattr(service_main, "APP_ENV", "development")
    monkeypatch.setattr(service_main, "AI_SERVICE_API_KEY", None)

    with caplog.at_level(logging.WARNING, logger=service_main.__name__):
        service_main._validate_startup_config()

    assert any(
        "AI_SERVICE_API_KEY not set" in record.getMessage()
        for record in caplog.records
    )


def test_ai_service_rejects_empty_key_when_configured(monkeypatch):
    """С настроенным ключом запрос без заголовка тоже должен получить 401.

    Регрессия: важно убедиться, что атакующий не обходит auth, просто не
    отправляя заголовок X-AI-Service-Key — раньше require_api_key мог
    пропустить такой запрос, если бы не сравнение со значением None.
    """
    monkeypatch.setattr(service_main, "AI_SERVICE_API_KEY", "secret")
    client = TestClient(service_main.app)

    response = client.post(
        "/ai/answer",
        json={
            "conversation_id": 1,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 401
