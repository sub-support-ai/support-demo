import json
from pathlib import Path

GOLD_PATH = Path("scripts/eval_data/kb_gold.json")
EVAL_DATA_DIR = Path("scripts/eval_data")


EXTRA_CASES = [
    # Пароль / учётная запись
    {
        "query": "после отпуска не могу войти в учетную запись, пароль не подходит",
        "expected_title": "Сброс пароля или разблокировка учётной записи",
    },
    {
        "query": "при входе пишет account locked, рабочая учетная запись заблокирована",
        "expected_title": "Сброс пароля или разблокировка учётной записи",
    },
    {
        "query": "пароль истек, не могу зайти в корпоративную систему",
        "expected_title": "Сброс пароля или разблокировка учётной записи",
    },
    # MFA
    {
        "query": "сменил телефон и теперь не могу пройти MFA",
        "expected_title": "Не приходит MFA-код или не работает подтверждение входа",
    },
    {
        "query": "не приходит push подтверждение входа в приложении",
        "expected_title": "Не приходит MFA-код или не работает подтверждение входа",
    },
    {
        "query": "двухфакторная авторизация не работает после замены смартфона",
        "expected_title": "Не приходит MFA-код или не работает подтверждение входа",
    },
    # VPN
    {
        "query": "VPN подключается, но внутренние сайты не открываются",
        "expected_title": "VPN не подключается: первичная диагностика",
    },
    {
        "query": "из дома не открываются корпоративные ресурсы через VPN",
        "expected_title": "VPN не подключается: первичная диагностика",
    },
    {
        "query": "VPN пишет timeout и не устанавливает соединение",
        "expected_title": "VPN не подключается: первичная диагностика",
    },
    # Доступ / 403
    {
        "query": "открываю корпоративный портал, пишет нет прав доступа",
        "expected_title": "Нет доступа к корпоративной системе или ошибка 403",
    },
    {
        "query": "после перевода в другой отдел пропал доступ к системе",
        "expected_title": "Нет доступа к корпоративной системе или ошибка 403",
    },
    {
        "query": "внутренняя система открывается, но нужный раздел недоступен",
        "expected_title": "Нет доступа к корпоративной системе или ошибка 403",
    },
    # почтовый клиент
    {
        "query": "письма не уходят из исходящих в почтовый клиент",
        "expected_title": "почтовый клиент не отправляет или не получает почту",
    },
    {
        "query": "почтовый клиент просит пароль снова и снова",
        "expected_title": "почтовый клиент не отправляет или не получает почту",
    },
    {
        "query": "почта перестала обновляться, новые письма не появляются",
        "expected_title": "почтовый клиент не отправляет или не получает почту",
    },
    # Wi-Fi
    {
        "query": "ноутбук видит Wi-Fi, но пишет без доступа к интернету",
        "expected_title": "Wi-Fi медленный, нестабильный или не подключается",
    },
    {
        "query": "в переговорной слабый Wi-Fi, видеозвонки зависают",
        "expected_title": "Wi-Fi медленный, нестабильный или не подключается",
    },
    {
        "query": "корпоративная сеть Wi-Fi просит пароль, но не подключает",
        "expected_title": "Wi-Fi медленный, нестабильный или не подключается",
    },
    # Медленный компьютер
    {
        "query": "после включения компьютера всё зависает и долго грузится",
        "expected_title": "Компьютер или ноутбук работает медленно",
    },
    {
        "query": "ноутбук стал тормозить после обновления",
        "expected_title": "Компьютер или ноутбук работает медленно",
    },
    {
        "query": "рабочий компьютер постоянно зависает при открытии браузера",
        "expected_title": "Компьютер или ноутбук работает медленно",
    },
    # ПО / лицензии
    {
        "query": "нужно установить программу для работы с PDF",
        "expected_title": "Установка корпоративного ПО или запрос лицензии",
    },
    {
        "query": "не хватает лицензии на корпоративное приложение",
        "expected_title": "Установка корпоративного ПО или запрос лицензии",
    },
    {
        "query": "нужно поставить разрешенное ПО из корпоративного каталога",
        "expected_title": "Установка корпоративного ПО или запрос лицензии",
    },
    # Принтер / МФУ
    {
        "query": "сканер на МФУ не отправляет документы на email",
        "expected_title": "Принтер или МФУ не печатает и не сканирует",
    },
    {
        "query": "печать зависла в очереди, документы не выходят",
        "expected_title": "Принтер или МФУ не печатает и не сканирует",
    },
    {
        "query": "МФУ показывает замятие бумаги, хотя бумаги внутри нет",
        "expected_title": "Принтер или МФУ не печатает и не сканирует",
    },
    # корпоративная ВКС / приложение видеосвязи
    {
        "query": "в приложение видеосвязи меня не слышат, микрофон не работает",
        "expected_title": "корпоративная ВКС или приложение видеосвязи: нет звука, камеры или подключения к встрече",
    },
    {
        "query": "корпоративная ВКС не подключается к встрече, бесконечная загрузка",
        "expected_title": "корпоративная ВКС или приложение видеосвязи: нет звука, камеры или подключения к встрече",
    },
    {
        "query": "камера в корпоративная ВКС черная, собеседники меня не видят",
        "expected_title": "корпоративная ВКС или приложение видеосвязи: нет звука, камеры или подключения к встрече",
    },
]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate_case(case: dict) -> None:
    if not case.get("query"):
        raise ValueError(f"Case without query: {case}")
    if not case.get("expected_title"):
        raise ValueError(f"Case without expected_title: {case}")


def normalize_case(case: dict) -> dict:
    return {
        "query": case["query"].strip(),
        "expected_title": case["expected_title"].strip(),
    }


def main() -> None:
    gold = load_json(GOLD_PATH)

    old_cases = gold.get("cases", [])
    old_normalized_cases = []
    for case in old_cases:
        validate_case(case)
        old_normalized_cases.append(normalize_case(case))

    additional_files = [
        path for path in sorted(EVAL_DATA_DIR.glob("kb_*.json")) if path.name != GOLD_PATH.name
    ]

    merged_cases = []
    seen = set()

    source_counts = {"kb_gold.json": len(old_cases)}

    def append_case(case: dict) -> None:
        validate_case(case)
        normalized = normalize_case(case)

        key = (
            normalized["query"].lower(),
            normalized["expected_title"].lower(),
        )

        if key in seen:
            return

        seen.add(key)
        merged_cases.append(normalized)

    for case in old_cases:
        append_case(case)

    for path in additional_files:
        data = load_json(path)
        cases = data.get("cases", [])
        source_counts[path.name] = len(cases)
        for case in cases:
            append_case(case)

    for case in EXTRA_CASES:
        append_case(case)

    current_version = int(gold.get("version", 1))
    next_version = current_version if old_normalized_cases == merged_cases else current_version + 1

    result = {
        "description": (
            "Gold-set для оценки качества KB-поиска. Каждый кейс — пара "
            "(естественный запрос пользователя, title ожидаемой статьи). "
            "Скрипт scripts/eval_kb.py гонит запросы через search_knowledge_articles "
            "и считает recall@1 / recall@3 / MRR."
        ),
        "version": next_version,
        "cases": merged_cases,
    }

    GOLD_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Готово. Было кейсов: {len(old_cases)}")
    for source, count in source_counts.items():
        if source == "kb_gold.json":
            continue
        print(f"Добавлено из {source}: {count}")
    print(f"Дополнительных IT-кейсов: {len(EXTRA_CASES)}")
    print(f"Итого в kb_gold.json: {len(merged_cases)}")
    print(f"Версия gold-set: {current_version} -> {next_version}")


if __name__ == "__main__":
    main()
