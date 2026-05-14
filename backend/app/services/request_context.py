from app.models.user import User

OFFICE_OPTIONS = ("Главный офис", "Склад", "Удаленно")
AFFECTED_ITEM_OPTIONS = (
    "Рабочее место",
    "Ноутбук",
    "Принтер/МФУ",
    "VPN",
    "1C",
    "Почта",
)

_OFFICE_EMAIL_HINTS = {
    "Главный офис": ("hq", "main", "office", "msk", "moscow"),
    "Склад": ("warehouse", "sklad", "store"),
    "Удаленно": ("remote", "home"),
}


def infer_office_from_email(email: str) -> str | None:
    normalized = email.lower()
    for office, hints in _OFFICE_EMAIL_HINTS.items():
        if any(hint in normalized for hint in hints):
            return office
    return None


def build_request_context(user: User) -> dict[str, object]:
    office = infer_office_from_email(user.email)
    return {
        "requester_name": user.username,
        "requester_email": user.email,
        "office": office,
        "office_source": "email" if office else None,
        "office_options": list(OFFICE_OPTIONS),
        "affected_item_options": list(AFFECTED_ITEM_OPTIONS),
    }
