"""
Двухуровневая таксономия:

- Внутренняя (Category) — 14 классов, на которых учится классификатор. Дробит
  it_software на install/error и it_access на grant/reset для лучшего сигнала
  при обучении и аналитики потоков обращений.

- Контрактная (ContractCategory) — 12 классов, фиксируется в
  RestAPI/docs/ai-lead-contract.md §3.2. Это то, что ai-service возвращает
  во внешний RestAPI.

Маппинг идёт через `to_contract_category()` — вызывается на стороне
ai-service в ответе `/ai/classify`, не в обучающих данных.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

Department = Literal["IT", "HR", "finance", "other"]

# Внутренняя таксономия (14 классов) — для обучения.
Category = Literal[
    "it_hardware",
    "it_software_install",
    "it_software_error",
    "it_access_grant",
    "it_access_reset",
    "it_network",
    "hr_payroll",
    "hr_leave",
    "hr_policy",
    "hr_onboarding",
    "finance_invoice",
    "finance_expense",
    "finance_report",
    "other",
]

# Контрактная таксономия (12 классов) — RestAPI/docs/ai-lead-contract.md §3.2.
ContractCategory = Literal[
    "it_hardware",
    "it_software",
    "it_access",
    "it_network",
    "hr_payroll",
    "hr_leave",
    "hr_policy",
    "hr_onboarding",
    "finance_invoice",
    "finance_expense",
    "finance_report",
    "other",
]

# Маппинг внутренних категорий в контрактные (схлопывание split'ов).
INTERNAL_TO_CONTRACT_CATEGORY: dict[Category, ContractCategory] = {
    "it_hardware": "it_hardware",
    "it_software_install": "it_software",
    "it_software_error": "it_software",
    "it_access_grant": "it_access",
    "it_access_reset": "it_access",
    "it_network": "it_network",
    "hr_payroll": "hr_payroll",
    "hr_leave": "hr_leave",
    "hr_policy": "hr_policy",
    "hr_onboarding": "hr_onboarding",
    "finance_invoice": "finance_invoice",
    "finance_expense": "finance_expense",
    "finance_report": "finance_report",
    "other": "other",
}

# Маппинг контрактных категорий в department — RestAPI/docs/ai-lead-contract.md §3.3.
CONTRACT_CATEGORY_TO_DEPARTMENT: dict[ContractCategory, Department] = {
    "it_hardware": "IT",
    "it_software": "IT",
    "it_access": "IT",
    "it_network": "IT",
    "hr_payroll": "HR",
    "hr_leave": "HR",
    "hr_policy": "HR",
    "hr_onboarding": "HR",
    "finance_invoice": "finance",
    "finance_expense": "finance",
    "finance_report": "finance",
    "other": "other",
}


def to_contract_category(internal: Category) -> ContractCategory:
    """Схлопнуть внутреннюю 14-категорию во внешнюю 12-категорию для ответа клиенту."""
    return INTERNAL_TO_CONTRACT_CATEGORY[internal]


def category_to_department(category: Category) -> Department:
    """Детерминированный маппинг внутренней категории в department по правилу контракта."""
    return CONTRACT_CATEGORY_TO_DEPARTMENT[INTERNAL_TO_CONTRACT_CATEGORY[category]]


Priority = Literal["критический", "высокий", "средний", "низкий"]

Persona = Literal[
    "бухгалтер",
    "инженер",
    "hr_специалист",
    "новичок",
    "удалёнщик",
    "руководитель",
]

Tone = Literal["спокойный", "раздражённый", "паникующий", "формальный"]

Length = Literal["короткий", "средний", "длинный"]


class Message(BaseModel):
    role: Literal["user", "agent"]
    text: str


class Ticket(BaseModel):
    title: str = Field(max_length=120)
    body: str
    steps_tried: Optional[str] = None


class Labels(BaseModel):
    department: Department
    category: Category
    priority: Priority


class Sample(BaseModel):
    conversation: List[Message] = Field(min_length=2, max_length=12)
    ticket: Ticket
    labels: Labels


class GenerationBatch(BaseModel):
    samples: List[Sample]


class JudgeVerdict(BaseModel):
    valid: bool
    label_match: bool
    issues: List[str] = Field(default_factory=list)
    corrected_labels: Optional[Labels] = None
