import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.knowledge_article import KnowledgeArticle, KnowledgeChunk
from app.services.knowledge_base import build_search_text


def _reviewed_now() -> datetime:
    return datetime.now(timezone.utc)


DEFAULT_ARTICLES = [
    {
        "department": "IT",
        "request_type": "VPN не работает",
        "title": "VPN не подключается: первичная проверка",
        "problem": "Пользователь не может подключиться к корпоративному VPN.",
        "symptoms": [
            "VPN не подключается",
            "ошибка удалённого доступа",
            "не приходит MFA-код",
            "профиль VPN не найден",
        ],
        "applies_to": {
            "systems": ["VPN", "MFA", "удалённый доступ"],
            "devices": ["ноутбук", "рабочая станция"],
            "offices": ["любой офис", "домашняя сеть"],
        },
        "steps": [
            "Проверьте, что интернет работает без VPN.",
            "Закройте VPN-клиент и откройте его заново.",
            "Убедитесь, что выбран корпоративный профиль подключения.",
            "Если запрашивается MFA-код, введите новый код из приложения.",
            "Если ошибка повторяется, зафиксируйте код ошибки и время последней попытки.",
        ],
        "when_to_escalate": (
            "создавать запрос, если есть ошибка 403/809, не приходит MFA-код, "
            "не найден профиль VPN или подключение не восстановилось после перезапуска клиента"
        ),
        "required_context": ["офис", "устройство", "логин", "код ошибки", "тип сети", "что уже пробовали"],
        "keywords": "vpn впн удаленный доступ подключение ошибка авторизация сеть mfa 403 809",
        "body": (
            "Проверьте интернет без VPN, перезапустите VPN-клиент, выберите корпоративный профиль "
            "и повторите вход с новым MFA-кодом."
        ),
        "owner": "IT support",
        "access_scope": "public",
    },
    {
        "department": "IT",
        "request_type": "Сброс пароля",
        "title": "Сброс пароля учётной записи",
        "problem": "Пользователь не может войти из-за пароля или блокировки учётной записи.",
        "symptoms": ["не могу войти", "забыл пароль", "учётная запись заблокирована", "ошибка авторизации"],
        "applies_to": {
            "systems": ["корпоративная учётная запись", "AD", "портал самообслуживания"],
            "devices": ["ноутбук", "рабочая станция"],
        },
        "steps": [
            "Проверьте раскладку клавиатуры и Caps Lock.",
            "Попробуйте войти через корпоративный портал самообслуживания.",
            "Если учётная запись заблокирована, подождите 15 минут и повторите вход.",
            "Для ручного сброса подготовьте логин, корпоративную почту и подтверждение личности.",
        ],
        "when_to_escalate": (
            "создавать запрос, если портал самообслуживания недоступен, пользователь не проходит MFA "
            "или учётная запись остаётся заблокированной"
        ),
        "required_context": ["логин", "корпоративная почта", "система входа", "текст ошибки"],
        "keywords": "пароль сброс вход учетная запись логин авторизация заблокирован mfa",
        "body": "Проверьте раскладку, Caps Lock и портал самообслуживания. Для ручного сброса нужны логин и почта.",
        "owner": "Identity team",
        "access_scope": "public",
    },
    {
        "department": "IT",
        "request_type": "Сломано оборудование",
        "title": "Принтер не печатает",
        "problem": "Документы не печатаются на офисном принтере или МФУ.",
        "symptoms": ["принтер не печатает", "документ застрял в очереди", "ошибка МФУ", "замятие бумаги"],
        "applies_to": {
            "systems": ["печать", "очередь печати"],
            "devices": ["принтер", "МФУ"],
            "offices": ["любой офис"],
        },
        "steps": [
            "Проверьте, что принтер включён и не показывает ошибку на дисплее.",
            "Убедитесь, что в лотке есть бумага и нет замятия.",
            "Очистите очередь печати и отправьте один тестовый документ.",
            "Если проблема осталась, укажите модель принтера, кабинет и текст ошибки.",
        ],
        "when_to_escalate": "создавать запрос, если есть аппаратная ошибка, замятие не устраняется или печать не восстанавливается",
        "required_context": ["офис", "кабинет", "модель принтера", "текст ошибки", "что уже пробовали"],
        "keywords": "принтер печать очередь документ мфу бумага картридж драйвер",
        "body": "Проверьте питание, бумагу, замятие и очередь печати. Затем отправьте тестовый документ.",
        "owner": "Workplace support",
        "access_scope": "public",
    },
    {
        "department": "IT",
        "request_type": "Доступ к системе",
        "title": "Ошибка 403 при входе в корпоративную систему",
        "problem": "Пользователь входит в систему, но получает отказ в доступе.",
        "symptoms": ["ошибка 403", "доступ запрещён", "не хватает прав", "нет роли"],
        "applies_to": {
            "systems": ["SAP", "1С", "корпоративный портал"],
            "devices": ["браузер", "рабочая станция"],
        },
        "steps": [
            "Проверьте, что входите под корпоративным логином.",
            "Зафиксируйте название системы и операцию, на которой появляется ошибка.",
            "Проверьте, есть ли у коллеги с такой же ролью доступ к той же операции.",
        ],
        "when_to_escalate": "создавать запрос, если роль действительно нужна для работы или ошибка повторяется у нескольких пользователей",
        "required_context": ["система", "логин", "нужная роль", "операция", "скриншот или текст ошибки"],
        "keywords": "403 доступ запрещен sap 1с система права роль вход",
        "body": "Ошибка 403 обычно означает нехватку прав. Для запроса нужны система, логин, роль и пример операции.",
        "owner": "Access management",
        "access_scope": "public",
    },
    {
        "department": "HR",
        "request_type": "HR-запрос",
        "title": "Как запросить справку с места работы",
        "problem": "Пользователю нужна HR-справка или кадровый документ.",
        "symptoms": ["нужна справка", "справка с места работы", "документ для банка", "документ для визы"],
        "applies_to": {
            "systems": ["HR"],
            "offices": ["любой офис"],
        },
        "steps": [
            "Укажите тип документа.",
            "Укажите период, если он нужен в справке.",
            "Укажите способ получения и дату, к которой документ нужен.",
            "Если справка нужна для банка или визы, добавьте требования к формулировке.",
        ],
        "when_to_escalate": "создавать запрос, если документ нужен в конкретный срок или требуется нестандартная формулировка",
        "required_context": ["тип документа", "период", "срок", "способ получения", "особые требования"],
        "keywords": "справка работа 2ндфл отпуск hr кадры документ",
        "body": "Для справки нужны тип документа, период, способ получения и срок.",
        "owner": "HR operations",
        "access_scope": "public",
    },
    {
        "department": "finance",
        "request_type": "Финансовый запрос",
        "title": "Статус оплаты счёта",
        "problem": "Пользователь хочет узнать статус оплаты счёта или платежа.",
        "symptoms": ["статус оплаты", "счёт не оплачен", "платёж не прошёл", "проверить оплату"],
        "applies_to": {
            "systems": ["финансы", "бухгалтерия"],
        },
        "steps": [
            "Подготовьте номер счёта или заказа.",
            "Укажите контрагента, сумму и дату отправки.",
            "Если платёж срочный, укажите крайний срок и основание срочности.",
        ],
        "when_to_escalate": "создавать запрос, если оплата влияет на срок поставки, закрытие периода или обязательства перед контрагентом",
        "required_context": ["номер счёта", "контрагент", "сумма", "дата отправки", "крайний срок"],
        "keywords": "оплата счет платеж финансы бухгалтерия статус заказ",
        "body": "Для проверки оплаты нужны номер счёта, контрагент, сумма и дата отправки.",
        "owner": "Finance operations",
        "access_scope": "public",
    },
]


def _build_chunk(article: KnowledgeArticle) -> str:
    parts = [
        article.problem or "",
        article.body,
        "\n".join(article.steps or []),
        article.when_to_escalate or "",
    ]
    return "\n".join(part for part in parts if part)


async def seed_knowledge_articles() -> None:
    created = 0
    updated = 0
    reviewed_at = _reviewed_now()
    expires_at = reviewed_at + timedelta(days=180)

    async with AsyncSessionLocal() as db:
        for item in DEFAULT_ARTICLES:
            item = {
                **item,
                "reviewed_at": reviewed_at,
                "expires_at": expires_at,
                "version": 1,
            }
            result = await db.execute(
                select(KnowledgeArticle).where(KnowledgeArticle.title == item["title"])
            )
            article = result.scalar_one_or_none()
            if article is None:
                article = KnowledgeArticle(**item, is_active=True)
                db.add(article)
                created += 1
            else:
                for key, value in item.items():
                    setattr(article, key, value)
                article.is_active = True
                updated += 1

            await db.flush()
            article.search_text = build_search_text(article)
            existing_chunk = await db.execute(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.article_id == article.id)
                .where(KnowledgeChunk.chunk_index == 0)
                .limit(1)
            )
            chunk = existing_chunk.scalar_one_or_none()
            if chunk is None:
                db.add(
                    KnowledgeChunk(
                        article_id=article.id,
                        chunk_index=0,
                        content=_build_chunk(article),
                        is_active=True,
                    )
                )
            else:
                chunk.content = _build_chunk(article)
                chunk.is_active = True

        await db.commit()

    print(f"Knowledge articles ready: created={created}, updated={updated}.")


if __name__ == "__main__":
    asyncio.run(seed_knowledge_articles())
