from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.constants.departments import DepartmentLiteral


class ResponseTemplateBase(BaseModel):
    department: DepartmentLiteral | None = None
    request_type: str | None = Field(default=None, max_length=50)
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=4000)
    is_active: bool = True

    @field_validator("request_type")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("title", "body")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field must not be empty")
        return value


class ResponseTemplateCreate(ResponseTemplateBase):
    pass


class ResponseTemplateRead(ResponseTemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime | None = None
