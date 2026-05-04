import os
import logging

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
from classifier import classify_ticket
from answerer import generate_answer

app = FastAPI()
logger = logging.getLogger(__name__)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", os.getenv("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")
OLLAMA_HEALTH_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_HEALTH_TIMEOUT_SECONDS", "3"))

# ========================
# Схемы для /ai/classify
# ========================
class TicketRequest(BaseModel):
    ticket_id: int
    title: str
    body: str

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
    content: str

class AnswerRequest(BaseModel):
    conversation_id: int
    messages: list[ChatMessage]

class Source(BaseModel):
    title: str
    url: str | None = None

class AnswerResponse(BaseModel):
    answer: str
    confidence: float
    escalate: bool
    sources: list[Source] = Field(default_factory=list)
    model_version: str

# ========================
# Эндпоинты
# ========================
@app.post("/ai/classify", response_model=ClassifyResponse)
def classify(request: TicketRequest):
    try:
        result = classify_ticket(
            ticket_id=request.ticket_id,
            title=request.title,
            body=request.body
        )
        return result
    except Exception as e:
        logger.exception("AI classify failed")
        raise HTTPException(status_code=500, detail="ai_classify_failed") from e

@app.post("/ai/answer", response_model=AnswerResponse)
def answer(request: AnswerRequest):
    try:
        # Фильтруем system сообщения — защита от prompt injection
        safe_messages = [m for m in request.messages if m.role != "system"]
        
        result = generate_answer(
            conversation_id=request.conversation_id,
            messages=safe_messages
        )
        return result
    except Exception as e:
        logger.exception("AI answer failed")
        raise HTTPException(status_code=500, detail="ai_answer_failed") from e

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
            "detail": str(e),
        }
    except ValueError as e:
        return {
            "status": "degraded",
            "ollama": "invalid_response",
            "ollama_url": OLLAMA_BASE_URL,
            "model": OLLAMA_MODEL,
            "detail": str(e),
        }

    model_names = {item.get("name") for item in tags if isinstance(item, dict)}
    model_available = any(
        name == OLLAMA_MODEL or str(name).startswith(f"{OLLAMA_MODEL}:")
        for name in model_names
    )
    if not model_available:
        return {
            "status": "degraded",
            "ollama": "ok",
            "ollama_url": OLLAMA_BASE_URL,
            "model": OLLAMA_MODEL,
            "detail": "model_not_found",
        }

    return {
        "status": "ok",
        "ollama": "ok",
        "ollama_url": OLLAMA_BASE_URL,
        "model": OLLAMA_MODEL,
    }
