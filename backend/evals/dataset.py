"""Формат YAML-датасета и его загрузка.

Зачем YAML, а не JSON / CSV / JSONL:
- Человеку удобно читать и править: датасет растёт по мере того, как
  саппорт натыкается на промахи RAG в проде. CSV/JSON в редакторе с длинными
  русскими запросами читаются хуже.
- Поддерживает комментарии — можно оставить «# регрессия для тикета #427»
  рядом с конкретным кейсом.
- Списки и многострочные строки естественно выражаются в YAML (`|` для
  многострочного query, `-` для нескольких ожидаемых ответов).

Формат:

    # backend/evals/data/baseline.yaml
    cases:
      - query: "не работает VPN, не подключается"
        expected_titles:
          - "VPN не подключается"
        notes: "Базовый сценарий"

      - query: "забыл пароль, не могу зайти"
        expected_titles:
          - "Сброс пароля"

`expected_titles` — а не `expected_ids`, чтобы датасет был портабелен между
KB разных клиентов: id'шки не совпадают, а название статьи можно повторить
в seed-данных каждого окружения.

Сравнение нечёткое (точнее — case-insensitive): сравниваем нормализованные
title'ы. Это компромисс между точностью («exact match») и переносимостью
(«похожая статья называется чуть иначе»). При желании можно расширить на
fuzzy-match через difflib, но пока экстра-сложность не оправдана.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class EvalCase:
    """Один кейс из YAML-датасета."""

    query: str
    expected_titles: frozenset[str]
    notes: str | None = None


def normalize_title(title: str) -> str:
    """Каноничный вид title'а для сравнения: lower + сжатые пробелы.

    Используется и при загрузке датасета, и в runner'е — чтобы сравнение
    было симметричным: `"VPN не подключается"` из YAML матчится с тем же
    title'ом из БД.
    """
    return " ".join(title.strip().lower().split())


def load_dataset(path: Path | str) -> list[EvalCase]:
    """Загружает датасет из YAML-файла. Падает с понятной ошибкой при
    структурных проблемах (а не при первом NoneType.get())."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    cases_raw = raw.get("cases")
    if not isinstance(cases_raw, list):
        raise ValueError(
            f"{path}: ожидался ключ 'cases' со списком кейсов, получено: {type(cases_raw).__name__}"
        )

    cases: list[EvalCase] = []
    for index, item in enumerate(cases_raw):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: case #{index} должен быть mapping'ом")

        query = item.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"{path}: case #{index} — `query` обязателен, непустая строка")

        titles_raw = item.get("expected_titles") or item.get("expected_title")
        if isinstance(titles_raw, str):
            titles = (titles_raw,)
        elif isinstance(titles_raw, list):
            titles = tuple(titles_raw)
        else:
            raise ValueError(
                f"{path}: case #{index} — `expected_titles` обязательный список / строка"
            )
        if not titles:
            raise ValueError(f"{path}: case #{index} — `expected_titles` не может быть пустым")
        for t in titles:
            if not isinstance(t, str) or not t.strip():
                raise ValueError(
                    f"{path}: case #{index} — каждый expected_title должен быть непустой строкой"
                )

        cases.append(
            EvalCase(
                query=query.strip(),
                expected_titles=frozenset(normalize_title(t) for t in titles),
                notes=item.get("notes") if isinstance(item.get("notes"), str) else None,
            )
        )

    if not cases:
        raise ValueError(f"{path}: датасет пустой — добавьте хотя бы один case")

    return cases


def fixture_articles_for(cases: list[EvalCase]) -> list[dict[str, Any]]:
    """Возвращает список dict'ов с минимальными полями для seed'а KB.

    Хочется честный baseline: ни 1.0 (нечего улучшать), ни 0.0 (всё одинаково
    плохо). Поэтому имитируем реалистичный сценарий «админ KB добавил статью
    под одну формулировку, остальные пользовательские варианты RAG должен
    дотянуть сам»:

      - keywords = title + ПЕРВЫЙ query, который ссылается на эту статью
        (как будто админ создал статью именно под него).
      - Остальные query'и из эвал-набора — «новые формулировки», которые
        админ ещё не успел добавить. Они и есть проверка качества RAG:
        дотянет ли он за счёт title-токенов / FTS / семантики, или промажет.

    На таком fixture мы видим текущий уровень и каждое улучшение (query
    rewriting, reranker) — измеримо.
    """
    seen: set[str] = set()
    first_query_for: dict[str, str] = {}
    for case in cases:
        for title in case.expected_titles:
            first_query_for.setdefault(title, case.query)

    articles: list[dict[str, Any]] = []
    for case in cases:
        for title in case.expected_titles:
            if title in seen:
                continue
            seen.add(title)
            articles.append(
                {
                    "title": title,
                    "body": title,
                    "keywords": f"{title} {first_query_for[title]}",
                    "department": "IT",
                    "is_active": True,
                }
            )
    return articles
