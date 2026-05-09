"""Тесты PII-маскирования.

Проверяем:
  - mask_pii() корректно заменяет email и телефоны.
  - Идемпотентность: повторный вызов не меняет уже маскированный текст.
  - Текст без PII не изменяется.
  - HTTP-интеграция: body тикета, сохранённое через API, не содержит
    открытых email / телефонов.
"""

import pytest
from httpx import AsyncClient

from app.services.pii import mask_pii


# ── Unit: mask_pii ───────────────────────────────────────────────────────────


def test_masks_email():
    assert mask_pii("Напишите на user@example.com") == "Напишите на [email скрыт]"


def test_masks_email_mixed_case():
    assert "[email скрыт]" in mask_pii("Контакт: Admin.User+tag@Company.ORG")


def test_masks_russian_phone_with_plus():
    result = mask_pii("Звоните +7 (495) 123-45-67")
    assert "[телефон скрыт]" in result
    assert "123-45-67" not in result


def test_masks_russian_phone_eight_prefix():
    result = mask_pii("Номер: 8 800 555 35 35")
    assert "[телефон скрыт]" in result


def test_masks_russian_phone_compact():
    result = mask_pii("тел 79991234567 доп 101")
    assert "[телефон скрыт]" in result
    assert "9991234567" not in result


def test_masks_multiple_pii_in_text():
    text = "Пишите user@corp.ru или звоните +7-999-000-11-22"
    result = mask_pii(text)
    assert "[email скрыт]" in result
    assert "[телефон скрыт]" in result
    assert "user@corp.ru" not in result
    assert "999-000-11-22" not in result


def test_no_change_without_pii():
    text = "Проблема с принтером в кабинете 302. Пробовал перезагрузить."
    assert mask_pii(text) == text


def test_idempotent():
    text = "Контакт: user@example.com"
    once = mask_pii(text)
    twice = mask_pii(once)
    assert once == twice


def test_empty_string_unchanged():
    assert mask_pii("") == ""


def test_none_like_empty_is_safe():
    # На практике в БД None приходит не сюда, но строка None не ломает
    assert mask_pii("None") == "None"


# ── Integration: PII в body тикета через API ─────────────────────────────────


@pytest.mark.asyncio
async def test_ticket_body_pii_stripped_on_create(client: AsyncClient):
    """Тикет, созданный через POST /tickets/, хранит уже замаскированный body."""
    reg = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "pii-test@example.com",
            "username": "pii_user",
            "password": "Secret123!",
        },
    )
    assert reg.status_code == 201
    token = reg.json()["access_token"]

    resp = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "Тест PII",
            "body": "Свяжитесь со мной на john@corp.ru или 8 800 000 11 22",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    body = resp.json()["body"]
    assert "john@corp.ru" not in body
    assert "8 800 000 11 22" not in body
    assert "[email скрыт]" in body
    assert "[телефон скрыт]" in body
