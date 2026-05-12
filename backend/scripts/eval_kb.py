"""Eval KB-поиска на gold-set.

Зачем:
  - без метрик мы не знаем, ухудшил ли последний коммит качество поиска;
  - типичная ситуация: правка промпта или порога ломает recall, и мы
    замечаем это только в проде по жалобам;
  - этот скрипт — детерминированный «хелсчек качества» KB.

Метрики:
  - recall@1 — доля кейсов, где ожидаемая статья на первом месте.
    Главная метрика: пользователь видит топ-1, остальное обычно не читает.
  - recall@3 — доля кейсов, где ожидаемая статья в топ-3.
    Дополнительная: показывает, что статья хотя бы попадает в кандидаты.
  - MRR (Mean Reciprocal Rank) — среднее обратной позиции (1/rank).
    Чувствительна к различию между «в топ-1» и «в топ-3» — даёт более
    плавную картину чем recall@k.
  - mean_score — среднее значение KnowledgeMatch.score у правильных
    результатов. Полезно для калибровки RAG_SCORE_*_THRESHOLD.

Использование:

    python -m scripts.eval_kb
    python -m scripts.eval_kb --gold custom_set.json --top-k 5 --verbose

Без флагов берёт scripts/eval_data/kb_gold.json. С --verbose для каждого
кейса печатает топ-K с пометкой ✓/✗ — удобно для анализа неудач.

Дальнейшее развитие:
  - --diff-against runs/<previous_id>.json — сравнить с предыдущим
    прогоном, увидеть регрессии по конкретным кейсам;
  - сохранение результатов в БД для дашборда «качество KB по дням»;
  - расширение gold-set'а через автогенерацию из feedback'а реальных
    пользователей (когда накопится).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_GOLD_SET = Path(__file__).parent / "eval_data" / "kb_gold.json"
DEFAULT_ARTICLES_DIR = Path(__file__).parent / "seed_data" / "articles"


@dataclass
class CaseResult:
    query: str
    expected_title: str
    rank: int | None  # 1-based, None если не нашли в топ-K
    matched_score: float | None
    top_titles: list[str]


def _find_rank(matches: list[Any], expected_title: str) -> tuple[int | None, float | None]:
    expected_norm = expected_title.strip().lower()
    for index, match in enumerate(matches, start=1):
        if match.article.title.strip().lower() == expected_norm:
            return index, match.score
    return None, None


def _load_article_titles(articles_dir: Path) -> tuple[set[str], list[str]]:
    titles: set[str] = set()
    duplicates: list[str] = []
    seen: set[str] = set()

    if not articles_dir.exists():
        return titles, [f"Articles directory not found: {articles_dir}"]

    for path in sorted(articles_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, list):
            duplicates.append(f"{path.name}: root JSON value must be a list")
            continue
        for item in data:
            title = str(item.get("title", "")).strip()
            if not title:
                duplicates.append(f"{path.name}: article without title")
                continue
            if title in seen:
                duplicates.append(f"Duplicate article title: {title}")
            seen.add(title)
            titles.add(title)
    return titles, duplicates


def _validate_cases(cases: list[dict], article_titles: set[str]) -> list[str]:
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()

    for index, case in enumerate(cases, start=1):
        query = str(case.get("query", "")).strip()
        expected = str(case.get("expected_title", "")).strip()
        if not query:
            errors.append(f"Case #{index}: missing query")
        if not expected:
            errors.append(f"Case #{index}: missing expected_title")
        if query and expected:
            key = (query.lower(), expected.lower())
            if key in seen:
                errors.append(f"Case #{index}: duplicate query/expected pair")
            seen.add(key)
        if expected and article_titles and expected not in article_titles:
            errors.append(f"Case #{index}: expected_title not found in seed articles: {expected}")
    return errors


async def _run_case(query: str, expected_title: str, top_k: int) -> CaseResult:
    """Один прогон: search → проверяем где ожидаемая статья.

    Каждый кейс получает свежую сессию — изоляция от warm-up cache
    проблем других кейсов (наш кэш живёт между вызовами в процессе,
    поэтому повторный одинаковый query будет cache-hit, что нам и нужно
    для замера latency, но не аффектит качество).
    """
    from app.database import AsyncSessionLocal
    from app.services.knowledge_base import (
        KnowledgeSearchFilters,
        search_knowledge_articles,
    )

    async with AsyncSessionLocal() as db:
        # Без access_scope-фильтра — eval гоняем как админ, видим всё.
        filters = KnowledgeSearchFilters(access_scopes=("public", "internal"))
        matches = await search_knowledge_articles(db, query, limit=top_k, filters=filters)

    rank, score = _find_rank(matches, expected_title)
    return CaseResult(
        query=query,
        expected_title=expected_title,
        rank=rank,
        matched_score=score,
        top_titles=[m.article.title for m in matches],
    )


def _summary(results: list[CaseResult], top_k: int) -> dict:
    """Считает recall@1, recall@K, MRR и средний score правильных hit'ов."""
    total = len(results)
    hits_at_1 = sum(1 for r in results if r.rank == 1)
    hits_at_k = sum(1 for r in results if r.rank is not None)
    mrr = sum(1 / r.rank for r in results if r.rank) / total if total else 0.0
    matched_scores = [r.matched_score for r in results if r.matched_score is not None]
    mean_score = sum(matched_scores) / len(matched_scores) if matched_scores else 0.0
    return {
        "total_cases": total,
        f"recall@1": hits_at_1 / total if total else 0.0,
        f"recall@{top_k}": hits_at_k / total if total else 0.0,
        "mrr": mrr,
        "mean_match_score": mean_score,
        "misses": [
            {"query": r.query, "expected": r.expected_title, "got_top": r.top_titles[:3]}
            for r in results
            if r.rank is None
        ],
    }


def _print_human(summary: dict, results: list[CaseResult], verbose: bool, top_k: int) -> None:
    print(f"\nGold-set: {summary['total_cases']} кейсов")
    print(f"recall@1   : {summary['recall@1']:.1%}")
    print(f"recall@{top_k:<3}: {summary[f'recall@{top_k}']:.1%}")
    print(f"MRR        : {summary['mrr']:.3f}")
    print(f"mean score : {summary['mean_match_score']:.2f}")

    if verbose:
        print("\nДетали по кейсам:")
        for index, r in enumerate(results, start=1):
            mark = "✓" if r.rank == 1 else ("◯" if r.rank else "✗")
            rank_str = f"#{r.rank}" if r.rank else "miss"
            score_str = f", score={r.matched_score:.1f}" if r.matched_score is not None else ""
            print(f"{mark} [{index:>3}] {rank_str:>5}{score_str}  {r.query!r}")
            if r.rank != 1:
                print(f"       ожидали: {r.expected_title!r}")
                print(f"       топ-3:   {r.top_titles[:3]}")

    if summary["misses"]:
        print(f"\nMISSES ({len(summary['misses'])}):")
        for miss in summary["misses"]:
            print(f"  query:    {miss['query']!r}")
            print(f"  expected: {miss['expected']!r}")
            print(f"  got_top:  {miss['got_top']}")
            print()


async def run_eval(
    gold_path: Path,
    top_k: int,
    verbose: bool,
    output_json: Path | None,
    articles_dir: Path,
    skip_validation: bool,
    validate_only: bool,
    min_recall_at_1: float,
    min_recall_at_k: float,
) -> int:
    if not gold_path.exists():
        print(f"Gold-set не найден: {gold_path}", file=sys.stderr)
        return 1

    data = json.loads(gold_path.read_text(encoding="utf-8-sig"))
    cases = data.get("cases") or []
    if not cases:
        print("Gold-set пуст", file=sys.stderr)
        return 1
    if not isinstance(cases, list):
        print("Gold-set invalid: cases must be a list", file=sys.stderr)
        return 1

    if not skip_validation:
        article_titles, article_errors = _load_article_titles(articles_dir)
        validation_errors = article_errors + _validate_cases(cases, article_titles)
        if validation_errors:
            print("Gold-set validation failed:", file=sys.stderr)
            for error in validation_errors:
                print(f"  - {error}", file=sys.stderr)
            return 1

    if validate_only:
        print(f"Gold-set validation OK: {len(cases)} cases")
        return 0

    results: list[CaseResult] = []
    for case in cases:
        query = case.get("query")
        expected = case.get("expected_title")
        if not query or not expected:
            logger.warning("Пропускаю невалидный кейс: %s", case)
            continue
        result = await _run_case(query, expected, top_k)
        results.append(result)

    summary = _summary(results, top_k)
    _print_human(summary, results, verbose, top_k)

    if output_json:
        payload = {"summary": summary, "cases": [r.__dict__ for r in results]}
        output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nРезультат сохранён в {output_json}")

    if summary["recall@1"] < min_recall_at_1:
        return 1
    if summary[f"recall@{top_k}"] < min_recall_at_k:
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Eval KB-поиска на gold-set")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD_SET, help="Путь к gold-set JSON")
    parser.add_argument("--top-k", type=int, default=3, help="K для recall@K (default: 3)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Печатать каждый кейс")
    parser.add_argument("--output", type=Path, default=None, help="Сохранить результат в JSON")
    parser.add_argument(
        "--articles-dir",
        type=Path,
        default=DEFAULT_ARTICLES_DIR,
        help="Папка seed-статей для проверки expected_title",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Не проверять gold-set на дубли и отсутствующие статьи",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Только проверить gold-set и seed-статьи, без запросов к БД",
    )
    parser.add_argument(
        "--min-recall-at-1",
        type=float,
        default=0.5,
        help="Минимальный recall@1 для успешного exit code",
    )
    parser.add_argument(
        "--min-recall-at-k",
        type=float,
        default=0.0,
        help="Минимальный recall@K для успешного exit code",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    exit_code = asyncio.run(
        run_eval(
            args.gold,
            args.top_k,
            args.verbose,
            args.output,
            args.articles_dir,
            args.skip_validation,
            args.validate_only,
            args.min_recall_at_1,
            args.min_recall_at_k,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
