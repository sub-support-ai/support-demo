from pydantic import BaseModel, ConfigDict, EmailStr


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"   # стандартное поле — всегда "bearer"


class RequestContextDefaults(BaseModel):
    requester_name: str
    requester_email: EmailStr
    office: str | None = None
    office_source: str | None = None
    office_options: list[str]
    affected_item_options: list[str]


class UserMe(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    username: str
    role: str
    is_active: bool
    agent_id: int | None = None
    agent_department: str | None = None
    request_context: RequestContextDefaults | None = None
