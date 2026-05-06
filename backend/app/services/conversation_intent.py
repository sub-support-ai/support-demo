from dataclasses import dataclass
from enum import StrEnum


class ConversationIntent(StrEnum):
    ANSWER = "answer"
    CREATE_DRAFT = "create_draft"
    EMERGENCY = "emergency"


SUPPORT_DRAFT_INTENT_TERMS = (
    "тикет", "заявк", "черновик", "обращен", "запрос", "техподдерж", "тех поддерж",
    "специалист", "саппорт", "support",
)
SUPPORT_DRAFT_ACTION_TERMS = (
    "созда", "сформир", "оформ", "заведи", "завести", "отправ", "эскал",
)
URGENT_TERMS = (
    "срочно", "авар", "критич", "опасн", "горит", "дым", "искр",
)
PHYSICAL_INCIDENT_TERMS = (
    "провод", "кабел", "розетк", "удлинител", "электр", "питани", "сломал",
    "сломался", "порвал", "порвался", "оторвал", "поврежд",
)


@dataclass(frozen=True)
class ConversationState:
    intent: ConversationIntent
    requires_draft: bool
    answer_override: str | None = None
    confidence_cap: float | None = None


def detect_conversation_state(messages: list[dict[str, str]]) -> ConversationState:
    user_messages = [
        message.get("content", "").strip().lower()
        for message in messages
        if message.get("role") == "user" and message.get("content", "").strip()
    ]
    if not user_messages:
        return ConversationState(intent=ConversationIntent.ANSWER, requires_draft=False)

    latest = user_messages[-1]
    combined = "\n".join(user_messages)

    has_draft_action = any(term in latest for term in SUPPORT_DRAFT_ACTION_TERMS)
    has_draft_object = any(term in latest for term in SUPPORT_DRAFT_INTENT_TERMS)
    if has_draft_action and has_draft_object:
        return _draft_state(ConversationIntent.CREATE_DRAFT)

    has_urgent_context = any(term in combined for term in URGENT_TERMS)
    has_physical_incident = any(term in combined for term in PHYSICAL_INCIDENT_TERMS)
    if has_urgent_context and has_physical_incident:
        return _draft_state(ConversationIntent.EMERGENCY)

    return ConversationState(intent=ConversationIntent.ANSWER, requires_draft=False)


def _draft_state(intent: ConversationIntent) -> ConversationState:
    return ConversationState(
        intent=intent,
        requires_draft=True,
        answer_override=(
            "Соберу данные для черновика обращения. Из истории возьму описание проблемы "
            "и уже упомянутые действия. Уточните заявителя, офис и затронутый объект; "
            "после этого сформирую черновик для специалиста."
        ),
        confidence_cap=0.5,
    )
