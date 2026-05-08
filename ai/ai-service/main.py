import logging
import os

import requests
from fastapi import Depends, Header, HTTPException, FastAPI, status
from pydantic import BaseModel, Field
from typing import Literal
from classifier import classify_ticket
from answerer import generate_answer

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", os.getenv("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
OLLAMA_HEALTH_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_HEALTH_TIMEOUT_SECONDS", "3"))
OLLAMA_EMBED_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_EMBED_TIMEOUT_SECONDS", "60"))
APP_ENV = os.getenv("APP_ENV", "development")
AI_SERVICE_API_KEY = os.getenv("AI_SERVICE_API_KEY")


def _validate_startup_config() -> None:
    """Проверяет конфигурацию при старте — fail-closed для production.

    Без AI_SERVICE_API_KEY require_api_key пропускает все запросы. В
    production это означает, что любой, кто достучался до :8001, ходит в
    AI без аутентификации (а оттуда — к Ollama, к промптам, и потенциально
    к утечке данных клиента). Поэтому: если APP_ENV=production и ключ не
    задан — поднимаем RuntimeError на старте, чтобы упало громко и сразу,
    а не тихо открыло периметр.

    В development разрешаем пустой ключ для удобства локального запуска,
    но один раз пишем WARNING — чтобы dev-окружение случайно не уехало
    в production без ключа.
    """
    if APP_ENV == "production" and not AI_SERVICE_API_KEY:
        raise RuntimeError(
            "AI_SERVICE_API_KEY не задан при APP_ENV=production. "
            "Без него /ai/* открыт всем, кто достучался до сервиса. "
            "Сгенерируйте ключ и положите в переменные окружения."
        )
    if not AI_SERVICE_API_KEY:
        logger.warning(
            "AI_SERVICE_API_KEY not set — auth disabled. "
            "Acceptable for local development only; required in production."
        )


_validate_startup_config()
app = FastAPI()


def require_api_key(x_ai_service_key: str | None = Header(default=None)) -> None:
    if not AI_SERVICE_API_KEY:
        # Допустимо только в dev: см. _validate_startup_config — в production
        # сервис не стартует без ключа, поэтому сюда не дойдёт.
        return
    if x_ai_service_key != AI_SERVICE_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid AI service key",
        )

# ========================
# Схемы для /ai/classify
# ========================
class TicketRequest(BaseModel):
    ticket_id: int | None = Field(default=None, ge=1)
    title: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1, max_length=20000)

class ClassifyResponse(BaseModel):
    category: Literal[
        "it_hardware", "it_software", "it_access", "it_network",
        "hr_payroll", "hr_leave", "hr_policy", "hr_onboarding",
        "finance_invoice", "finance_expense", "finance_report",
        "other"
    ]
    department: Literal["IT", "HR", "finance", "other"]
    priority: Literal["критический", "высокий", "средний", "низкий"]
    confidence: float
    draft_response: str
    model_version: str

# ========================
# Схемы для /ai/answer
# ========================
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=10000)

class AnswerRequest(BaseModel):
    conversation_id: int = Field(..., ge=1)
    messages: list[ChatMessage] = Field(..., min_length=1, max_length=20)

class Source(BaseModel):
    title: str
    url: str | None = None

class AnswerResponse(BaseModel):
    answer: str
    confidence: float
    escalate: bool
    sources: list[Source] = []
    model_version: str


class EmbedRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=64)


class EmbedResponse(BaseModel):
    model: str
    embeddings: list[list[float]]

# ========================
# Эндпоинты
# ========================
@app.post("/ai/classify", response_model=ClassifyResponse, dependencies=[Depends(require_api_key)])
async def classify(request: TicketRequest):
    try:
        result = classify_ticket(
            ticket_id=request.ticket_id,
            title=request.title,
            body=request.body
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ai/answer", response_model=AnswerResponse, dependencies=[Depends(require_api_key)])
async def answer(request: AnswerRequest):
    try:
        # Фильтруем system сообщения — защита от prompt injection
        safe_messages = [m for m in request.messages if m.role != "system"]
        
        result = generate_answer(
            conversation_id=request.conversation_id,
            messages=safe_messages
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ai/embed", response_model=EmbedResponse, dependencies=[Depends(require_api_key)])
async def embed(request: EmbedRequest):
    texts = [text.strip() for text in request.texts if text.strip()]
    if not texts:
        raise HTTPException(status_code=422, detail="texts must contain at least one non-empty item")

    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/embed",
            json={
                "model": OLLAMA_EMBED_MODEL,
                "input": texts,
                "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
            },
            timeout=OLLAMA_EMBED_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.HTTPError as exc:
        if exc.response is None or exc.response.status_code != 404:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        payload = _embed_with_legacy_api(texts)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    embeddings = payload.get("embeddings")
    if embeddings is None and "embedding" in payload:
        embeddings = [payload["embedding"]]
    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        raise HTTPException(status_code=502, detail="invalid embedding response")

    return {"model": OLLAMA_EMBED_MODEL, "embeddings": embeddings}


def _embed_with_legacy_api(texts: list[str]) -> dict:
    embeddings: list[list[float]] = []
    for text in texts:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            json={"model": OLLAMA_EMBED_MODEL, "prompt": text},
            timeout=OLLAMA_EMBED_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        embedding = payload.get("embedding")
        if not isinstance(embedding, list):
            raise HTTPException(status_code=502, detail="invalid embedding response")
        embeddings.append(embedding)
    return {"embeddings": embeddings}

@app.get("/healthcheck")
def healthcheck():
    try:
        response = requests.get(
            f"{OLLAMA_BASE_URL}/api/tags",
            timeout=OLLAMA_HEALTH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        tags = response.json().get("models", [])
    except requests.RequestException as e:
        return {
            "status": "degraded",
            "ollama": "unavailable",
            "ollama_url": OLLAMA_BASE_URL,
            "model": OLLAMA_MODEL,
            "embed_model": OLLAMA_EMBED_MODEL,
            "detail": str(e),
        }
    except ValueError as e:
        return {
            "status": "degraded",
            "ollama": "invalid_response",
            "ollama_url": OLLAMA_BASE_URL,
            "model": OLLAMA_MODEL,
            "embed_model": OLLAMA_EMBED_MODEL,
            "detail": str(e),
        }

    model_names = {item.get("name") for item in tags if isinstance(item, dict)}
    model_available = _ollama_model_available(model_names, OLLAMA_MODEL)
    embed_model_available = _ollama_model_available(model_names, OLLAMA_EMBED_MODEL)
    if not model_available:
        return {
            "status": "degraded",
            "ollama": "ok",
            "ollama_url": OLLAMA_BASE_URL,
            "model": OLLAMA_MODEL,
            "embed_model": OLLAMA_EMBED_MODEL,
            "detail": "model_not_found",
        }
    if not embed_model_available:
        return {
            "status": "degraded",
            "ollama": "ok",
            "ollama_url": OLLAMA_BASE_URL,
            "model": OLLAMA_MODEL,
            "embed_model": OLLAMA_EMBED_MODEL,
            "detail": "embed_model_not_found",
        }

    return {
        "status": "ok",
        "ollama": "ok",
        "ollama_url": OLLAMA_BASE_URL,
        "model": OLLAMA_MODEL,
        "embed_model": OLLAMA_EMBED_MODEL,
    }


def _ollama_model_available(model_names: set[object], expected_model: str) -> bool:
    return any(
        name == expected_model or str(name).startswith(f"{expected_model}:")
        for name in model_names
    )
