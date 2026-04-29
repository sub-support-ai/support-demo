from datetime import datetime
import re

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,31}$")
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


class UserBase(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=32)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        if not USERNAME_RE.fullmatch(value):
            raise ValueError(
                "Логин должен быть 3-32 символа: латиница, цифры, точка, "
                "дефис или подчёркивание; первый символ — буква или цифра"
            )
        return value


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
