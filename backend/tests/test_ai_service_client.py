from app.config import get_settings
from app.services.ai_service_client import ai_service_headers


def test_ai_service_headers_empty_without_key(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.delenv("AI_SERVICE_API_KEY", raising=False)

    assert ai_service_headers() == {}

    get_settings.cache_clear()


def test_ai_service_headers_include_configured_key(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("AI_SERVICE_API_KEY", "local-secret")

    assert ai_service_headers() == {"X-AI-Service-Key": "local-secret"}

    get_settings.cache_clear()
