from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator
from typing import Literal
from classifier import classify_ticket
from answerer import generate_answer

app = FastAPI()

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
    sources: list[Source] = []
    model_version: str

# ========================
# Эндпоинты
# ========================
@app.post("/ai/classify", response_model=ClassifyResponse)
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

@app.post("/ai/answer", response_model=AnswerResponse)
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

@app.get("/healthcheck")
def healthcheck():
    return {"status": "ok"}