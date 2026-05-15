from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ConditionOp = Literal[
    "eq",
    "neq",
    "contains",
    "not_contains",
    "gte",
    "lte",
    "gt",
    "lt",
    "in",
    "is_empty",
    "is_not_empty",
]

ActionType = Literal[
    "set_ai_priority",
    "override_sla_minutes",
    "add_comment",
    "reassign_department",
    "escalate_to_senior",
    "set_field",
]

AutomationTrigger = Literal[
    "ticket_confirmed",
    "ticket_reopened",
    "ticket_no_reply",
    "ticket_escalated",
]


class AutomationCondition(BaseModel):
    field: str = Field(min_length=1, max_length=100)
    op: ConditionOp
    value: Any = None


class AutomationAction(BaseModel):
    type: ActionType
    value: Any = None
    # только для type=set_field
    field: str | None = Field(default=None, max_length=100)


class AutomationRuleBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    is_active: bool = True
    priority: int = Field(default=100, ge=0, le=9999)
    trigger: AutomationTrigger
    conditions: list[AutomationCondition] = []
    actions: list[AutomationAction] = Field(min_length=1)


class AutomationRuleCreate(AutomationRuleBase):
    pass


class AutomationRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    is_active: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=9999)
    trigger: AutomationTrigger | None = None
    conditions: list[AutomationCondition] | None = None
    actions: list[AutomationAction] | None = Field(default=None, min_length=1)


class AutomationRuleRead(AutomationRuleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
