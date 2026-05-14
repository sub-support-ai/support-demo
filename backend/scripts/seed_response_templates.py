import asyncio

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.response_template import ResponseTemplate

DEFAULT_TEMPLATES = [
    {
        "department": "IT",
        "request_type": "VPN не работает",
        "title": "VPN: первичная диагностика",
        "body": (
            "Здравствуйте, {requester_name}.\n\n"
            "Проверяем проблему с VPN для объекта: {affected_item}.\n"
            "Локация: {office}.\n\n"
            "Пожалуйста, оставьте VPN-клиент открытым. Если появится код ошибки, "
            "добавьте его в запрос. Начинаю диагностику подключения и профиля доступа."
        ),
    },
    {
        "department": "IT",
        "request_type": "Сброс пароля",
        "title": "Сброс пароля: подтверждение",
        "body": (
            "Здравствуйте, {requester_name}.\n\n"
            "Приняли запрос на сброс пароля. Проверяем учетную запись и права доступа.\n"
            "Уточнение: {request_details}.\n\n"
            "После проверки сообщим дальнейшие действия в этом запросе."
        ),
    },
    {
        "department": "IT",
        "request_type": "Сломано оборудование",
        "title": "Оборудование: диагностика",
        "body": (
            "Здравствуйте, {requester_name}.\n\n"
            "Приняли запрос по оборудованию: {affected_item}.\n"
            "Офис: {office}. Детали: {request_details}.\n\n"
            "Проверим возможность удаленной диагностики. Если потребуется замена, "
            "зафиксируем это в запросе и передадим ответственному специалисту."
        ),
    },
    {
        "department": "HR",
        "request_type": "HR-запрос",
        "title": "HR: запрос принят",
        "body": (
            "Здравствуйте, {requester_name}.\n\n"
            "HR-запрос принят в работу. Тема: {request_details}.\n"
            "Проверим данные и вернемся с ответом в этом запросе."
        ),
    },
    {
        "department": "finance",
        "request_type": "Финансовый запрос",
        "title": "Финансы: запрос принят",
        "body": (
            "Здравствуйте, {requester_name}.\n\n"
            "Финансовый запрос принят. Документ или операция: {request_details}.\n"
            "Проверим информацию и сообщим следующий шаг."
        ),
    },
    {
        "department": None,
        "request_type": None,
        "title": "Общее: запрос в работе",
        "body": (
            "Здравствуйте, {requester_name}.\n\n"
            "Запрос принят в работу. Контекст: {request_type}; {request_details}.\n"
            "Если появятся дополнительные детали, добавьте их в этот запрос."
        ),
    },
]


async def seed_response_templates() -> None:
    created = 0
    updated = 0

    async with AsyncSessionLocal() as db:
        for item in DEFAULT_TEMPLATES:
            result = await db.execute(
                select(ResponseTemplate).where(
                    ResponseTemplate.department == item["department"],
                    ResponseTemplate.request_type == item["request_type"],
                    ResponseTemplate.title == item["title"],
                )
            )
            template = result.scalar_one_or_none()
            if template is None:
                template = ResponseTemplate(**item, is_active=True)
                db.add(template)
                created += 1
            else:
                template.body = item["body"]
                template.is_active = True
                updated += 1

        await db.commit()

    print(f"Response templates ready: created={created}, updated={updated}.")


if __name__ == "__main__":
    asyncio.run(seed_response_templates())
