"""
Service catalog — единственный источник правды о типах обращений.

Каждый CatalogItem описывает:
  - как распознать намерение пользователя (trigger_terms)
  - какие поля нужно собрать перед созданием черновика (required_fields)
  - какой вопрос задавать для каждого поля (field_questions)
  - в каком отделе KB искать ответ (kb_department)

Добавление нового типа обращения = добавление одного элемента в CATALOG.
Никаких изменений в conversation_ai, роутерах или миграциях не требуется.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Вопросы по умолчанию для стандартных полей — переопределяются в CatalogItem.
FIELD_QUESTIONS: dict[str, str] = {
    "username":         "Укажите ваш логин или ФИО (для поиска учётной записи).",
    "office":           "Укажите офис и номер кабинета.",
    "error_code":       "Укажите код или текст ошибки (можно скопировать с экрана).",
    "affected_system":  "Укажите название системы или программы (например: 1С, SAP, Outlook).",
    "operation":        "Какую операцию выполняете? (например: открыть отчёт, сохранить документ)",
    "device_description": "Опишите устройство: что именно, модель и инвентарный номер (если есть).",
    "software_name":    "Укажите название программы и версию (если знаете).",
    "justification":    "Для чего нужно? Укажите задачу или проект.",
    "sender_email":     "Укажите адрес отправителя подозрительного письма.",
    "already_clicked":  "Вы уже перешли по ссылке или открыли вложение? (да / нет)",
    "description":      "Опишите подробнее: что именно произошло и когда вы это заметили.",
    "device_type":      "Какое устройство потеряли: ноутбук, телефон или флешка?",
    "serial_number":    "Укажите серийный номер (на наклейке снизу или в учёте IT).",
    "circumstances":    "Опишите: где и когда потеряли или обнаружили пропажу.",
    "document_type":    "Какой документ нужен? (например: 2-НДФЛ, справка с места работы для банка)",
    "delivery_date":    "К какой дате нужен документ?",
    "purpose":          "Для чего нужен документ? (банк, виза, суд и т.д.)",
    "vacation_start":   "Укажите дату начала отпуска.",
    "vacation_end":     "Укажите дату окончания отпуска.",
    "vacation_type":    "Тип отпуска: ежегодный оплачиваемый, за свой счёт или другой?",
    "item_description": "Опишите что нужно закупить: наименование, характеристики, количество.",
    "budget":           "Ориентировочная стоимость или бюджет?",
    "phone":            "Укажите контактный телефон.",
}


@dataclass(frozen=True)
class CatalogItem:
    code: str
    department: str                        # "IT" | "HR" | "finance" | "security"
    title: str
    trigger_terms: tuple[str, ...]         # подстроки для поиска в сообщении (lowercase)
    required_fields: tuple[str, ...]       # порядок опроса
    field_questions: dict[str, str] = field(default_factory=dict)
    kb_department: str | None = None       # фильтр для RAG-поиска
    is_emergency: bool = False             # влияет на приоритет черновика

    def question_for(self, field_name: str) -> str:
        return self.field_questions.get(field_name, FIELD_QUESTIONS.get(field_name, f"Укажите {field_name}."))

    def next_missing(self, collected: dict[str, str]) -> str | None:
        for f in self.required_fields:
            if not collected.get(f, "").strip():
                return f
        return None

    def all_collected(self, collected: dict[str, str]) -> bool:
        return self.next_missing(collected) is None


CATALOG: list[CatalogItem] = [
    CatalogItem(
        code="vpn_connect",
        department="IT",
        title="VPN не подключается",
        trigger_terms=("vpn", "впн", "удалённый доступ", "удаленный доступ", "remote access"),
        required_fields=("username", "office", "error_code"),
        kb_department="IT",
    ),
    CatalogItem(
        code="password_reset",
        department="IT",
        title="Сброс пароля учётной записи",
        trigger_terms=(
            "сброс пароля", "забыл пароль", "не могу войти",
            "заблокировали учётку", "заблокирована учетка", "учётка заблокирована",
            "не помню пароль", "reset password",
        ),
        required_fields=("username", "affected_system"),
        kb_department="IT",
    ),
    CatalogItem(
        code="password_1c",
        department="IT",
        title="Пароль 1С / SAP",
        trigger_terms=(
            "пароль 1с", "пароль от 1с", "войти в 1с", "1с заблокировал",
            "1с не пускает", "sap пароль", "пароль sap", "зайти в 1с",
        ),
        required_fields=("username", "office"),
        field_questions={
            "username": "Укажите логин в 1С или табельный номер.",
            "office":   "Укажите офис и подразделение (например: Москва, бухгалтерия).",
        },
        kb_department="IT",
    ),
    CatalogItem(
        code="hardware_replace",
        department="IT",
        title="Замена или ремонт оборудования",
        trigger_terms=(
            "монитор", "сгорел", "сломался ноутбук", "не работает ноутбук",
            "клавиатура сломалась", "мышь сломалась", "оборудование сломалось",
            "не включается компьютер", "замена оборудования", "ремонт оборудования",
        ),
        required_fields=("username", "office", "device_description"),
        kb_department="IT",
    ),
    CatalogItem(
        code="software_install",
        department="IT",
        title="Установка программного обеспечения",
        trigger_terms=(
            "установить программу", "установить по", "нужна программа",
            "поставить приложение", "лицензия на", "скачать программу",
        ),
        required_fields=("username", "office", "software_name", "justification"),
        kb_department="IT",
    ),
    CatalogItem(
        code="access_403",
        department="IT",
        title="Ошибка доступа / нет прав",
        trigger_terms=(
            "ошибка 403", "нет доступа", "доступ запрещён", "доступ запрещен",
            "нет прав", "отказано в доступе", "не хватает прав", "права доступа",
        ),
        required_fields=("username", "affected_system", "operation"),
        kb_department="IT",
    ),
    CatalogItem(
        code="phishing_report",
        department="security",
        title="Подозрительное письмо / фишинг",
        trigger_terms=(
            "фишинг", "подозрительное письмо", "странная ссылка",
            "мошенническое письмо", "просят пароль в письме", "скам",
        ),
        required_fields=("username", "sender_email", "already_clicked"),
        field_questions={
            "already_clicked": "Вы уже перешли по ссылке, открыли вложение или ввели данные? (да / нет — это важно для определения срочности)",
        },
        kb_department="security",
        is_emergency=True,
    ),
    CatalogItem(
        code="security_incident",
        department="security",
        title="Инцидент информационной безопасности",
        trigger_terms=(
            "вирус", "взломали", "троян", "антивирус нашел", "антивирус обнаружил",
            "утечка данных", "подозрительная активность", "ransomware", "шифровальщик",
            "малварь", "malware",
        ),
        required_fields=("username", "office", "description"),
        field_questions={
            "description": "Опишите что произошло: что нашёл антивирус (если есть), когда заметили, что делали до этого.",
        },
        kb_department="security",
        is_emergency=True,
    ),
    CatalogItem(
        code="device_lost",
        department="security",
        title="Потеря или кража рабочего устройства",
        trigger_terms=(
            "потерял ноутбук", "украли телефон", "украли ноутбук",
            "потерял устройство", "пропал ноутбук", "потерял флешку",
        ),
        required_fields=("username", "device_type", "serial_number", "circumstances"),
        kb_department="security",
        is_emergency=True,
    ),
    CatalogItem(
        code="hr_certificate",
        department="HR",
        title="Справка с места работы",
        trigger_terms=(
            "справка с места работы", "справка 2-ндфл", "2ндфл",
            "справка для банка", "кадровый документ", "справка об отпуске",
            "справка о зарплате",
        ),
        required_fields=("username", "document_type", "delivery_date", "purpose"),
        kb_department="HR",
    ),
    CatalogItem(
        code="hr_vacation",
        department="HR",
        title="Оформление отпуска",
        trigger_terms=(
            "оформить отпуск", "взять отпуск", "заявление на отпуск",
            "плановый отпуск", "ежегодный отпуск", "отпуск за свой счёт",
        ),
        required_fields=("username", "vacation_start", "vacation_end", "vacation_type"),
        kb_department="HR",
    ),
    CatalogItem(
        code="finance_purchase",
        department="finance",
        title="Заявка на закупку оборудования или ПО",
        trigger_terms=(
            "купить оборудование", "заявка на закупку", "нужно купить",
            "заказ оборудования", "закупка по", "приобрести лицензию",
        ),
        required_fields=("username", "item_description", "budget", "justification"),
        kb_department="finance",
    ),
]

# Быстрый lookup по code
_CATALOG_BY_CODE: dict[str, CatalogItem] = {item.code: item for item in CATALOG}


def get_catalog_item(code: str) -> CatalogItem | None:
    return _CATALOG_BY_CODE.get(code)


def detect_catalog_item(messages: list[dict[str, str]]) -> CatalogItem | None:
    """Определяет тип обращения по последним сообщениям пользователя.

    Возвращает CatalogItem с наибольшим количеством совпавших trigger_terms,
    или None если ни один элемент каталога не подходит.
    """
    user_texts = [
        m.get("content", "").strip().lower()
        for m in messages
        if m.get("role") == "user" and m.get("content", "").strip()
    ]
    if not user_texts:
        return None

    # Ищем в последних 3 сообщениях пользователя
    search_space = " ".join(user_texts[-3:])

    best_item: CatalogItem | None = None
    best_score = 0

    for item in CATALOG:
        score = sum(1 for term in item.trigger_terms if term in search_space)
        if score > best_score:
            best_score = score
            best_item = item

    return best_item if best_score >= 1 else None
