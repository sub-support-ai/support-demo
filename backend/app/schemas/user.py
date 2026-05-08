from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


USERNAME_MAX_LENGTH = 100
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


class UserBase(BaseModel):
    email: EmailStr
    username: str = Field(min_length=1, max_length=USERNAME_MAX_LENGTH)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        username = value.strip()
        if not username:
            raise ValueError("Логин не должен быть пустым")
        return username


class UserCreate(UserBase):
    # min_length/max_length — потолок против DoS-обжора (мегабайтный "пароль"
    # заставил бы SHA-256 молоть впустую и забил бы JSON-парсер).
    # Ограничения bcrypt в 72 байта здесь НЕ валидируем: security.py
    # пропускает пароль через SHA-256 → hex (64 ASCII байта) перед bcrypt,
    # поэтому длинные и не-ASCII пароли работают корректно.
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if any(ch.isspace() for ch in value):
            raise ValueError("Пароль не должен содержать пробелы")
        if not any(ch.islower() for ch in value):
            raise ValueError("Пароль должен содержать строчную букву")
        if not any(ch.isupper() for ch in value):
            raise ValueError("Пароль должен содержать заглавную букву")
        if not any(ch.isdigit() for ch in value):
            raise ValueError("Пароль должен содержать цифру")
        if not any(not ch.isalnum() for ch in value):
            raise ValueError("Пароль должен содержать спецсимвол")
        return value


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime | None = None


class UserRoleUpdate(BaseModel):
    """Полезная нагрузка PATCH /users/{id}/role — смена роли админом.

    Список ролей закрытый: за пределами {user, agent, admin} ничего не
    работает (RBAC проверяет именно эти строки в require_role).
    Pydantic вернёт 422 на любой другой ввод — это лучше, чем сохранить
    "manager" и потом удивляться, почему у пользователя нет прав.
    """

    role: str = Field(pattern="^(user|agent|admin)$")
