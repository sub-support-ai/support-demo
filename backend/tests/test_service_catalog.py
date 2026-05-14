"""
Тесты service_catalog + intake flow в conversation_ai.

Покрывают:
  - detect_catalog_item: правильный выбор по trigger_terms
  - изоляция: "пароль 1С" не пересекается с BitLocker/security-статьями
  - "монитор сгорел" → hardware_replace
  - нейтральные сообщения → None (без каталога)
  - прогрессивный сбор полей (_run_intake_step)
  - _build_draft_payload: резюме содержит все нужные поля
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.service_catalog import (
    CatalogItem,
    detect_catalog_item,
    get_catalog_item,
    CATALOG,
)
from app.services.conversation_ai import (
    _build_draft_payload,
    _last_user_message,
    _resolve_catalog_item,
)


# ── detect_catalog_item ───────────────────────────────────────────────────────

def _msgs(*texts: str) -> list[dict]:
    return [{"role": "user", "content": t} for t in texts]


def test_detect_vpn():
    item = detect_catalog_item(_msgs("VPN не подключается, что делать?"))
    assert item is not None
    assert item.code == "vpn_connect"


def test_detect_password_1c():
    item = detect_catalog_item(_msgs("пароль от 1С не подходит, система не пускает"))
    assert item is not None
    assert item.code == "password_1c"


def test_detect_hardware_replace_monitor():
    item = detect_catalog_item(_msgs("монитор не включается, наверное сгорел"))
    assert item is not None
    assert item.code == "hardware_replace"


def test_detect_hardware_replace_laptop():
    item = detect_catalog_item(_msgs("сломался ноутбук, не запускается"))
    assert item is not None
    assert item.code == "hardware_replace"


def test_detect_phishing():
    item = detect_catalog_item(_msgs("получил подозрительное письмо со странной ссылкой"))
    assert item is not None
    assert item.code == "phishing_report"


def test_detect_access_403():
    item = detect_catalog_item(_msgs("при открытии отчёта ошибка 403, нет доступа"))
    assert item is not None
    assert item.code == "access_403"


def test_detect_hr_certificate():
    item = detect_catalog_item(_msgs("нужна справка 2-ндфл для банка"))
    assert item is not None
    assert item.code == "hr_certificate"


def test_detect_hr_vacation():
    item = detect_catalog_item(_msgs("хочу оформить отпуск с 1 июля"))
    assert item is not None
    assert item.code == "hr_vacation"


def test_detect_finance_purchase():
    item = detect_catalog_item(_msgs("нужно купить оборудование для нового сотрудника"))
    assert item is not None
    assert item.code == "finance_purchase"


def test_detect_neutral_returns_none():
    """Нейтральное сообщение без триггеров не должно давать совпадений."""
    item = detect_catalog_item(_msgs("как долго хранятся архивные документы?"))
    assert item is None


def test_detect_empty_returns_none():
    assert detect_catalog_item([]) is None
    assert detect_catalog_item([{"role": "assistant", "content": "Привет"}]) is None


# ── Изоляция: пароль 1С не должен находить security/BitLocker ────────────────

def test_password_1c_department_is_it_not_security():
    """Каталожный элемент 'пароль 1С' направляет RAG в IT, а не security."""
    item = detect_catalog_item(_msgs("пароль от 1С не работает"))
    assert item is not None
    assert item.code == "password_1c"
    assert item.kb_department == "IT"
    assert item.department == "IT"


def test_security_incident_is_emergency():
    item = detect_catalog_item(_msgs("антивирус обнаружил вирус на компьютере"))
    assert item is not None
    assert item.code == "security_incident"
    assert item.is_emergency is True
    assert item.kb_department == "security"


def test_device_lost_requires_correct_fields():
    item = get_catalog_item("device_lost")
    assert item is not None
    assert "device_type" in item.required_fields
    assert "serial_number" in item.required_fields
    assert item.is_emergency is True


# ── CatalogItem.next_missing / all_collected ──────────────────────────────────

def test_next_missing_returns_first_empty():
    item = get_catalog_item("vpn_connect")
    assert item.next_missing({}) == "username"
    assert item.next_missing({"username": "ivanov"}) == "office"
    assert item.next_missing({"username": "ivanov", "office": "HQ"}) == "error_code"
    assert item.next_missing({"username": "ivanov", "office": "HQ", "error_code": "809"}) is None


def test_all_collected_true_when_complete():
    item = get_catalog_item("vpn_connect")
    assert item.all_collected({"username": "x", "office": "y", "error_code": "z"}) is True
    assert item.all_collected({"username": "x", "office": "y"}) is False


def test_whitespace_only_not_counted_as_collected():
    item = get_catalog_item("vpn_connect")
    assert item.next_missing({"username": "  ", "office": "HQ", "error_code": "809"}) == "username"


def test_question_for_uses_override():
    item = get_catalog_item("password_1c")
    q = item.question_for("username")
    assert "табельный" in q or "логин" in q.lower()


def test_question_for_falls_back_to_field_questions():
    item = get_catalog_item("vpn_connect")
    q = item.question_for("username")
    assert len(q) > 5


# ── _build_draft_payload ──────────────────────────────────────────────────────

def test_build_draft_payload_contains_all_fields():
    item = get_catalog_item("vpn_connect")
    collected = {"username": "ivanov", "office": "Москва, кab.301", "error_code": "809"}
    payload = _build_draft_payload(item, collected)
    assert payload["escalate"] is True
    assert payload["catalog_code"] == "vpn_connect"
    assert "ivanov" in payload["answer"]
    assert "809" in payload["answer"]
    assert "Москва" in payload["answer"]


def test_build_draft_payload_emergency_has_warning():
    item = get_catalog_item("security_incident")
    collected = {
        "username": "petrov",
        "office": "HQ",
        "description": "антивирус нашёл троян",
    }
    payload = _build_draft_payload(item, collected)
    assert "Срочный" in payload["answer"] or "⚠" in payload["answer"]


# ── get_catalog_item ──────────────────────────────────────────────────────────

def test_get_catalog_item_by_code():
    assert get_catalog_item("vpn_connect") is not None
    assert get_catalog_item("nonexistent") is None


def test_all_catalog_items_have_valid_structure():
    """Каждый элемент каталога: есть поля, есть вопросы, dept не пустой."""
    for item in CATALOG:
        assert item.code
        assert item.department in {"IT", "HR", "finance", "security"}, item.code
        assert len(item.required_fields) > 0, item.code
        for field_name in item.required_fields:
            q = item.question_for(field_name)
            assert len(q) > 5, f"{item.code}: нет вопроса для поля {field_name}"


# ── _last_user_message ────────────────────────────────────────────────────────

def test_last_user_message_returns_last():
    history = [
        {"role": "user", "content": "первый"},
        {"role": "assistant", "content": "ответ"},
        {"role": "user", "content": "второй"},
    ]
    assert _last_user_message(history) == "второй"


def test_last_user_message_none_if_no_user():
    assert _last_user_message([{"role": "assistant", "content": "hi"}]) is None
    assert _last_user_message([]) is None


# ── _resolve_catalog_item ──────────────────────────────────────────────────────

def test_resolve_uses_existing_catalog_code():
    conv = MagicMock()
    conv.catalog_code = "vpn_connect"
    item = _resolve_catalog_item(conv, [])
    assert item is not None
    assert item.code == "vpn_connect"


def test_resolve_falls_back_to_detect():
    conv = MagicMock()
    conv.catalog_code = None
    item = _resolve_catalog_item(conv, _msgs("монитор сгорел"))
    assert item is not None
    assert item.code == "hardware_replace"


def test_resolve_returns_none_for_neutral():
    conv = MagicMock()
    conv.catalog_code = None
    item = _resolve_catalog_item(conv, _msgs("расскажи про регламент командировок"))
    assert item is None
