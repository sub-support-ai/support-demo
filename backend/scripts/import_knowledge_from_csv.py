"""Импорт статей KB из CSV.

Типичный сценарий: ServiceNow / SharePoint List / Excel-выгрузка от
заказчика. Контракт колонок гибкий — поддерживаем mapping через --map,
чтобы не требовать переименования заголовков в Excel.

Минимальный CSV (заголовки в первой строке):

    title,department,body
    "VPN не подключается",IT,"Полное описание решения..."
    "Запрос отпуска",HR,"Откройте HR-портал..."

Расширенный CSV (полный набор полей):

    title,department,request_type,body,problem,steps,when_to_escalate,
    required_context,keywords,owner,access_scope,source_url

Поля-списки (steps, symptoms, required_context):
  - принимают либо JSON-массив (`["a", "b", "c"]`),
  - либо строку с разделителем `;` (`a; b; c`).

applies_to (вложенный JSON):
  - принимается JSON-объект: `{"systems": ["VPN"], "devices": ["ноутбук"]}`.

Маппинг колонок (если у клиента свои названия):

    --map title=Subject,department=Group,body=Description

Использование:

    python -m scripts.import_knowledge_from_csv kb_export.csv
    python -m scripts.import_knowledge_from_csv kb.csv --delimiter ';' --encoding cp1251
    python -m scripts.import_knowledge_from_csv kb.csv --map "title=Subject,department=Group"
    python -m scripts.import_knowledge_from_csv kb.csv --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys
from pathlib import Path
from typing import Any

from app.database import AsyncSessionLocal
from app.services.knowledge_ingestion import bulk_upsert_knowledge_articles

logger = logging.getLogger(__name__)

# Поля, которые мы умеем разворачивать из строкового CSV-формата в list/dict.
_LIST_FIELDS = {"steps", "symptoms", "required_context"}
_DICT_FIELDS = {"applies_to"}


def _parse_list_field(value: str) -> list[str] | None:
    """Поле-список: JSON-массив либо `;`-разделитель."""
    value = value.strip()
    if not value:
        return None

    # Сначала JSON — он строже и приоритетней.
    if value.startswith("["):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            logger.debug("Не получилось распарсить как JSON-массив: %s", value[:100])

    # Fallback: разделитель `;`.
    return [item.strip() for item in value.split(";") if item.strip()]


def _parse_dict_field(value: str) -> dict | None:
    """Поле-объект: только JSON. Без JSON парсить не пытаемся, чтобы
    случайно не превратить строку в дикт со странными ключами."""
    value = value.strip()
    if not value:
        return None
    try:
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        logger.warning("applies_to ожидался JSON-объект, получили: %s", value[:100])
    return None


def _normalize_row(row: dict[str, str], col_map: dict[str, str]) -> dict[str, Any] | None:
    """Применяет маппинг колонок и приводит типы.

    col_map — {target_field: source_column}. Если source_column нет в строке,
    target_field не попадёт в результат.

    Возвращает None для строк, где не нашлось title — пропускаем без падения,
    т.к. CSV из реального мира часто содержит мусорные строки (заголовки
    разделов, пустые промежутки).
    """
    article: dict[str, Any] = {}
    for target, source in col_map.items():
        if source not in row:
            continue
        value = (row[source] or "").strip()
        if not value:
            continue
        if target in _LIST_FIELDS:
            parsed_list = _parse_list_field(value)
            if parsed_list:
                article[target] = parsed_list
        elif target in _DICT_FIELDS:
            parsed_dict = _parse_dict_field(value)
            if parsed_dict:
                article[target] = parsed_dict
        elif target == "is_active":
            article[target] = value.lower() in {"1", "true", "yes", "y", "да"}
        elif target == "version":
            try:
                article[target] = int(value)
            except ValueError:
                logger.warning("version='%s' не int, пропускаем поле", value)
        else:
            article[target] = value

    if not article.get("title"):
        return None
    return article


def _parse_col_map(spec: str | None) -> dict[str, str]:
    """`--map title=Subject,department=Group` → {"title": "Subject", ...}.

    Если --map не передан — возвращаем identity-маппинг (target == source).
    """
    if not spec:
        return {}
    pairs: dict[str, str] = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"Невалидный --map элемент: {part!r}, ожидается target=source")
        target, source = part.split("=", 1)
        pairs[target.strip()] = source.strip()
    return pairs


def _identity_col_map(headers: list[str]) -> dict[str, str]:
    """Если --map не передан, считаем, что заголовки CSV совпадают с именами полей."""
    return {header: header for header in headers}


async def import_csv(
    path: Path,
    *,
    delimiter: str = ",",
    encoding: str = "utf-8",
    col_map_spec: str | None = None,
    dry_run: bool = False,
) -> None:
    user_map = _parse_col_map(col_map_spec)

    with path.open(encoding=encoding, newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        if not reader.fieldnames:
            print(f"{path}: CSV без заголовков", file=sys.stderr)
            return
        # Полный маппинг = пользовательский поверх identity.
        col_map = {**_identity_col_map(reader.fieldnames), **user_map}

        rows_total = 0
        parsed: list[dict] = []
        skipped: list[int] = []
        for line_no, row in enumerate(reader, start=2):  # +1 за заголовок
            rows_total += 1
            article = _normalize_row(row, col_map)
            if article is None:
                skipped.append(line_no)
                continue
            parsed.append(article)

    if skipped:
        logger.info(
            "Пропущено %d строк без title (номера: %s%s)",
            len(skipped),
            ", ".join(str(n) for n in skipped[:10]),
            "…" if len(skipped) > 10 else "",
        )
    print(f"Распарсили {len(parsed)} статей из {rows_total} строк")

    if dry_run:
        print("(--dry-run, в БД ничего не записываем)")
        if parsed:
            print("Пример первой статьи:")
            example = {k: v for k, v in parsed[0].items() if k in {"title", "department", "request_type"}}
            print(json.dumps(example, ensure_ascii=False, indent=2))
        return

    if not parsed:
        return

    async with AsyncSessionLocal() as db:
        created, updated = await bulk_upsert_knowledge_articles(db, parsed)
        await db.commit()

    print(f"Импорт завершён: created={created}, updated={updated}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Импорт KB из CSV")
    parser.add_argument("csv_path", type=Path, help="Путь к CSV")
    parser.add_argument("--delimiter", default=",", help="Разделитель колонок (default: ,)")
    parser.add_argument("--encoding", default="utf-8", help="Кодировка (default: utf-8)")
    parser.add_argument(
        "--map",
        dest="col_map",
        default=None,
        help='Маппинг "target=source,..." — например "title=Subject,department=Group"',
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if not args.csv_path.exists():
        print(f"Файл не найден: {args.csv_path}", file=sys.stderr)
        sys.exit(1)

    asyncio.run(
        import_csv(
            args.csv_path,
            delimiter=args.delimiter,
            encoding=args.encoding,
            col_map_spec=args.col_map,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
