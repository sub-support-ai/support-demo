"""Импорт статей KB из Markdown-файлов с YAML frontmatter.

Типичный сценарий: клиент держит инструкции в Confluence или в Git-папке
с MD-файлами. Confluence умеет экспортировать страницу в Markdown
("Export to Markdown" plugin). Git-репозиторий с MD — частая практика
для команд, любящих docs-as-code.

Формат файла (frontmatter — обязательный блок YAML, потом тело Markdown):

    ---
    department: IT
    request_type: VPN не работает
    title: VPN не подключается: первичная проверка
    keywords: vpn впн mfa 403
    owner: IT support
    access_scope: public
    when_to_escalate: создавать запрос, если ошибка повторяется...
    required_context: [офис, устройство, логин, код ошибки]
    symptoms:
      - VPN не подключается
      - не приходит MFA-код
    applies_to:
      systems: [VPN, MFA]
      devices: [ноутбук]
    steps:
      - Проверьте, что интернет работает без VPN
      - Закройте VPN-клиент и откройте его заново
    ---

    # VPN не подключается

    Подробное описание проблемы и решения. Может быть много абзацев,
    может быть Markdown-форматирование (списки, заголовки). Эта часть
    идёт целиком в KnowledgeArticle.body — для FTS, как «полный текст».

Маппинг полей:
  - frontmatter ключ → поле KnowledgeArticle (1:1, см. _ALLOWED_FIELDS
    в knowledge_ingestion.py);
  - первый H1 в теле (#) — резерв на title, если frontmatter без него;
  - body — всё после frontmatter, обрезается по _MAX_BODY_CHARS.

Использование:

    python -m scripts.import_knowledge_from_markdown ./kb/

  --pattern "*.md"    — изменить glob (по умолчанию **/*.md, рекурсивно)
  --dry-run           — проверить файлы без записи в БД

Идемпотентно: тот же импорт второй раз обновит существующие статьи.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from app.database import AsyncSessionLocal
from app.services.knowledge_ingestion import bulk_upsert_knowledge_articles

logger = logging.getLogger(__name__)

# Лимит на тело статьи. KnowledgeArticle.body — Text, ограничен схемой
# на 8000 символов (см. KnowledgeArticleBase.body). Импорт обрезает до
# того же лимита и пишет в лог предупреждение.
_MAX_BODY_CHARS = 8000

# Frontmatter — YAML между двумя `---` в начале файла.
_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(?P<frontmatter>.*?)\n---\s*\n(?P<body>.*)\Z",
    re.DOTALL,
)
_FIRST_H1_RE = re.compile(r"^#\s+(?P<title>.+)$", re.MULTILINE)


def _parse_markdown(path: Path) -> dict[str, Any] | None:
    """Парсит один MD-файл в dict для bulk_upsert.

    Возвращает None, если файл невалидный (нет frontmatter, нет title и т.п.) —
    вызывающий код пропустит файл и продолжит импорт. Логи объясняют, что
    именно не так: иначе при импорте 500 файлов из Confluence трудно понять,
    почему статья не появилась.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Cannot read %s: %s", path, exc)
        return None

    match = _FRONTMATTER_RE.match(raw)
    if not match:
        logger.warning("%s: нет YAML frontmatter (---), пропускаем", path)
        return None

    try:
        frontmatter = yaml.safe_load(match.group("frontmatter")) or {}
    except yaml.YAMLError as exc:
        logger.warning("%s: невалидный YAML frontmatter: %s", path, exc)
        return None

    if not isinstance(frontmatter, dict):
        logger.warning(
            "%s: frontmatter должен быть dict, получили %s", path, type(frontmatter).__name__
        )
        return None

    body_md = match.group("body").strip()

    # title из frontmatter, иначе — первый H1, иначе — пропускаем.
    title = frontmatter.get("title")
    if not title:
        h1 = _FIRST_H1_RE.search(body_md)
        if h1:
            title = h1.group("title").strip()
            # Удаляем H1 из тела, чтобы не дублировать в title и body.
            body_md = body_md.replace(h1.group(0), "", 1).strip()
    if not title:
        logger.warning("%s: ни frontmatter.title, ни первый H1 не найдены — пропускаем", path)
        return None

    if len(body_md) > _MAX_BODY_CHARS:
        logger.warning(
            "%s: body длиной %d символов обрезан до %d",
            path,
            len(body_md),
            _MAX_BODY_CHARS,
        )
        body_md = body_md[:_MAX_BODY_CHARS]

    article = dict(frontmatter)
    article["title"] = title
    article["body"] = body_md
    # source_url — путь к исходному файлу, чтобы было видно происхождение.
    # Если у клиента это git-репо с MD — ссылка ведёт прямо на файл.
    article.setdefault("source_url", str(path))
    return article


def _collect_markdown_files(root: Path, pattern: str) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(root.rglob(pattern))


async def import_markdown_directory(
    directory: Path, pattern: str = "*.md", dry_run: bool = False
) -> None:
    files = _collect_markdown_files(directory, pattern)
    if not files:
        print(f"В {directory} не найдено файлов по шаблону {pattern!r}")
        return

    parsed: list[dict] = []
    for path in files:
        article = _parse_markdown(path)
        if article is not None:
            parsed.append(article)

    print(f"Распарсили {len(parsed)} статей из {len(files)} файлов")
    if dry_run:
        print("(--dry-run, в БД ничего не записываем)")
        return

    if not parsed:
        return

    async with AsyncSessionLocal() as db:
        created, updated = await bulk_upsert_knowledge_articles(db, parsed)
        await db.commit()

    print(f"Импорт завершён: created={created}, updated={updated}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Импорт KB из MD-файлов")
    parser.add_argument("directory", type=Path, help="Папка с MD-файлами или один файл")
    parser.add_argument("--pattern", default="*.md", help="Glob-шаблон файлов (default: *.md)")
    parser.add_argument(
        "--dry-run", action="store_true", help="Не записывать в БД, только проверить парсинг"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="DEBUG-логи")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if not args.directory.exists():
        print(f"Путь не существует: {args.directory}", file=sys.stderr)
        sys.exit(1)

    asyncio.run(import_markdown_directory(args.directory, args.pattern, args.dry_run))


if __name__ == "__main__":
    main()
