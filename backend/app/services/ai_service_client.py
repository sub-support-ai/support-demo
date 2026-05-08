from app.config import get_settings


def ai_service_headers() -> dict[str, str]:
    settings = get_settings()
    secret = settings.AI_SERVICE_API_KEY
    if secret is None:
        return {}
    # SecretStr.get_secret_value() — единственный способ извлечь значение
    # наружу. Не подменяем строкой ниже без оборачивания в SecretStr,
    # иначе dump объекта Settings потечёт ключом в логи.
    return {"X-AI-Service-Key": secret.get_secret_value()}
