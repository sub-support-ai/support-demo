from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    event_type: str
    title: str
    body: str
    target_type: str | None = None
    target_id: int | None = None
    is_read: bool
    created_at: datetime
    read_at: datetime | None = None


class NotificationUnreadCount(BaseModel):
    unread_count: int = Field(ge=0)
