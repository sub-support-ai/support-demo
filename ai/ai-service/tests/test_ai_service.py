import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))
sys.modules.setdefault(
    "requests",
    types.SimpleNamespace(
        RequestException=Exception,
        HTTPError=Exception,
        Timeout=TimeoutError,
        post=lambda *_args, **_kwargs: None,
        get=lambda *_args, **_kwargs: None,
    ),
)

answerer = importlib.import_module("answerer")
classifier = importlib.import_module("classifier")
service_main = importlib.import_module("main")


class _BrokenJsonResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"message": {"content": "not json"}}


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
        lambda *_args, **_kwargs: _BrokenJsonResponse(),
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
