from app.config import get_settings


def ai_service_headers() -> dict[str, str]:
    settings = get_settings()
    if not settings.AI_SERVICE_API_KEY:
        return {}
    return {"X-AI-Service-Key": settings.AI_SERVICE_API_KEY}
