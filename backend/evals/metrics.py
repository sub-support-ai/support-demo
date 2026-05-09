"""Метрики для оценки RAG-retrieval'а.

Все функции — чистые, без зависимости от БД и конкретного формата хранения
датасета. Это позволяет использовать их и в pytest-регрессии (на встроенном
mini-dataset), и в CLI-прогоне на реальной KB заказчика, и в ad-hoc Jupyter
для разовых замеров.

Терминология:
  retrieved — упорядоченный список идентификаторов статей, как их вернул
              search_knowledge_articles (top-k).
  expected  — set ожидаемых правильных идентификаторов. Несколько правильных
              ответов допустимы (один и тот же запрос может удовлетворить
              разные статьи KB).

Идентификаторы намеренно generic'и (TypeVar): на уровне метрик неважно,
сравниваем мы int-id'шки, slug'и или нормализованные title'ы.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class QueryReport:
    """Результат прогона одного запроса через retrieval."""

    query: str
    expected: frozenset
    retrieved: tuple
    rank: int | None  # 1-based rank первого правильного, или None если не нашли


@dataclass(frozen=True)
class EvalReport:
    """Сводный отчёт по всему датасету."""

    total: int
    precision_at_1: float
    recall_at_5: float
    mrr: float
    miss_count: int  # сколько запросов не нашли ни одной правильной статьи в top-k
    per_query: tuple[QueryReport, ...]


def first_match_rank(retrieved: Sequence[T], expected: Iterable[T]) -> int | None:
    """1-based позиция первой правильной статьи в retrieved.

    None — если ни одна expected-статья не попала в retrieved. Это намеренно
    отдельный случай (а не «бесконечный rank»): MRR-знаменатель честно
    учитывает «не нашли» как 0, а не как 1/inf.
    """
    expected_set = set(expected)
    for index, item in enumerate(retrieved, start=1):
        if item in expected_set:
            return index
    return None


def precision_at_k(retrieved: Sequence[T], expected: Iterable[T], k: int) -> float:
    """Доля правильных среди top-k. На самом деле для retrieval-задачи нас
    обычно интересует precision@1 (попал ли первый ответ), потому что
    пользователь видит именно его. Но передаваемый k — общий случай.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    expected_set = set(expected)
    top_k = retrieved[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for item in top_k if item in expected_set)
    return hits / len(top_k)


def recall_at_k(retrieved: Sequence[T], expected: Iterable[T], k: int) -> float:
    """Доля expected-статей, нашедшихся в top-k.

    Если expected пустой — формально recall не определён (делим на 0). Возвращаем
    1.0 как «все 0 ожидаемых статей найдены»: иначе пустой кейс портит среднее.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    expected_set = set(expected)
    if not expected_set:
        return 1.0
    top_k = set(retrieved[:k])
    return len(expected_set & top_k) / len(expected_set)


def reciprocal_rank(retrieved: Sequence[T], expected: Iterable[T]) -> float:
    """1 / rank, где rank — позиция первой правильной статьи. 0 если не нашли.

    Усреднение по датасету даёт MRR — стандартная метрика для retrieval-систем,
    у которых пользователь видит обычно первый результат, но иногда смотрит и
    дальше. Чувствительна к падению с rank=1 на rank=2 (1.0 → 0.5).
    """
    rank = first_match_rank(retrieved, expected)
    return 1.0 / rank if rank is not None else 0.0


def aggregate_reports(per_query: Sequence[QueryReport], k: int = 5) -> EvalReport:
    """Считает среднее по списку QueryReport.

    Если per_query пустой — возвращаем нули вместо ZeroDivisionError, иначе
    стартовый эвал-набор с 0 записей при ошибке загрузки YAML давал бы
    непонятное падение в середине отчёта.
    """
    total = len(per_query)
    if total == 0:
        return EvalReport(
            total=0,
            precision_at_1=0.0,
            recall_at_5=0.0,
            mrr=0.0,
            miss_count=0,
            per_query=tuple(per_query),
        )

    precision_sum = 0.0
    recall_sum = 0.0
    mrr_sum = 0.0
    miss = 0

    for report in per_query:
        precision_sum += precision_at_k(report.retrieved, report.expected, 1)
        recall_sum += recall_at_k(report.retrieved, report.expected, k)
        mrr_sum += reciprocal_rank(report.retrieved, report.expected)
        if report.rank is None:
            miss += 1

    return EvalReport(
        total=total,
        precision_at_1=precision_sum / total,
        recall_at_5=recall_sum / total,
        mrr=mrr_sum / total,
        miss_count=miss,
        per_query=tuple(per_query),
    )


def format_report(report: EvalReport) -> str:
    """Человекочитаемое представление отчёта для CLI / pytest-фейлов."""
    lines = [
        f"Total queries: {report.total}",
        f"  precision@1: {report.precision_at_1:.3f}",
        f"  recall@5:    {report.recall_at_5:.3f}",
        f"  MRR:         {report.mrr:.3f}",
        f"  Misses:      {report.miss_count} / {report.total}",
    ]
    if report.miss_count > 0:
        lines.append("")
        lines.append("Missed queries (нет правильной статьи в top-5):")
        for q in report.per_query:
            if q.rank is None:
                expected_preview = ", ".join(map(str, sorted(q.expected)))[:80]
                lines.append(f"  - {q.query!r} → expected: [{expected_preview}]")
    return "\n".join(lines)
