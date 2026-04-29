from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class AuditLogRead(BaseModel):
    """Одна запись аудита — то, что возвращается админу через GET /audit."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: Optional[int]
    action: str
    target_type: Optional[str]
    target_id: Optional[int]
    ip: Optional[str]
    # details хранится в БД как JSON-строка — для админа отдаём как есть.
    # Если понадобится фронту структурированный объект, распарсим на фронте
    # (json.parse на одной записи — копейки; на сервере парсинг 100 строк —
    # лишняя работа, особенно если админу нужен просто список).
    details: Optional[str]
    created_at: datetime
