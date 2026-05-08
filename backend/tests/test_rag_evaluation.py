"""Регрессионная оценка RAG-retrieval на baseline-датасете.

Главная цель этого файла:
- Зафиксировать минимально-приемлемые метрики (precision@1, recall@5, MRR)
  на наборе реалистичных запросов.
- Любая правка ranking (новые поля в скоре, веса FTS/semantic, чанкинг)
  не должна ронять эти метрики — иначе это регрессия, обсуждаемая в PR.

Подход:
- Сидим в SQLite (тестовое окружение conftest.py) с минимальным набором
  статей: для каждой ожидаемой статьи из YAML создаём KnowledgeArticle с
  title=body=keywords=<title>. Этого достаточно для FTS-fallback'а в
  knowledge_base.py.
- Прогоняем все query через search_knowledge_articles, собираем top-5,
  сравниваем по нормализованным title'ам.
- Считаем агрегаты, бьём pytest-fail если хотя бы одна метрика упала
  ниже зафиксированного порога.

Пороги намеренно сдержанные: датасет минимальный (15 кейсов), на FTS-only
без semantic-ветки (SQLite не поддерживает pgvector). На Postgres + semantic
+ полная KB цифры будут выше; этот тест — нижний граничный контракт.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_article import KnowledgeArticle
from app.services.knowledge_base import search_knowledge_articles

from evals.dataset import (
    EvalCase,
    fixture_articles_for,
    load_dataset,
    normalize_title,
)
from evals.metrics import (
    QueryReport,
    aggregate_reports,
    first_match_rank,
    format_report,
)


BASELINE_DATASET = Path(__file__).resolve().parents[1] / "evals" / "data" / "baseline.yaml"

# Минимально-приемлемые пороги на baseline-датасете в SQLite (FTS-only).
# Зафиксированы первым прогоном эталонного retrieval'а: precision@1=0.80,
# recall@5=0.80, MRR=0.80 (3 misses из 15 — длинные перефразировки типа
# «впн отвалился» и «wi-fi есть, но страницы не грузятся», которые без
# query rewriting / семантики FTS не вытягивает).
#
# Любая регрессия ниже этих цифр — повод разобраться, а не просто понизить
# порог. Любое улучшение (query rewriting, reranker, расширение KB) —
# повод поднять пороги.
MIN_PRECISION_AT_1 = 0.75
MIN_RECALL_AT_5 = 0.75
MIN_MRR = 0.75


@pytest.fixture
def baseline_cases() -> list[EvalCase]:
    return load_dataset(BASELINE_DATASET)


@pytest.fixture
async def seeded_kb(db_session: AsyncSession, baseline_cases) -> AsyncSession:
    """Сидит KB минимальным набором статей, покрывающим expected_titles."""
    for article_payload in fixture_articles_for(baseline_cases):
        db_session.add(KnowledgeArticle(**article_payload))
    await db_session.flush()
    return db_session


@pytest.mark.asyncio
async def test_baseline_meets_quality_thresholds(seeded_kb, baseline_cases):
    """Полный прогон baseline через search_knowledge_articles + проверка порогов.

    Если этот тест упал — НЕ снижайте пороги без обсуждения. Это регрессия:
    выясните, какая правка ranking'а её внесла, и почему она оправдана
    (например, могли пожертвовать precision@1 ради точности на длинном tail'е).
    """
    per_query: list[QueryReport] = []
    for case in baseline_cases:
        matches = await search_knowledge_articles(seeded_kb, case.query, limit=5)
        retrieved = tuple(normalize_title(m.article.title) for m in matches)
        rank = first_match_rank(retrieved, case.expected_titles)
        per_query.append(
            QueryReport(
                query=case.query,
                expected=case.expected_titles,
                retrieved=retrieved,
                rank=rank,
            )
        )

    report = aggregate_reports(per_query, k=5)

    # Печатаем отчёт всегда — pytest -s покажет; на падении ассертов он
    # тоже всплывёт в сообщении.
    print()
    print(format_report(report))

    assert report.precision_at_1 >= MIN_PRECISION_AT_1, (
        f"precision@1 упал до {report.precision_at_1:.3f} (минимум {MIN_PRECISION_AT_1}).\n"
        f"{format_report(report)}"
    )
    assert report.recall_at_5 >= MIN_RECALL_AT_5, (
        f"recall@5 упал до {report.recall_at_5:.3f} (минимум {MIN_RECALL_AT_5}).\n"
        f"{format_report(report)}"
    )
    assert report.mrr >= MIN_MRR, (
        f"MRR упал до {report.mrr:.3f} (минимум {MIN_MRR}).\n{format_report(report)}"
    )


# ── Юнит-тесты модулей evals (без БД) ───────────────────────────────────────


def test_metrics_first_match_rank_handles_no_match():
    from evals.metrics import first_match_rank

    assert first_match_rank(["a", "b"], ["x"]) is None
    assert first_match_rank(["a", "b", "c"], ["c"]) == 3
    assert first_match_rank(["a", "b"], ["a", "b"]) == 1


def test_metrics_recall_with_empty_expected_returns_one():
    from evals.metrics import recall_at_k

    # Пустой expected = «все 0 ожидаемых найдены», иначе пустой кейс
    # ломал бы среднее на разнородных датасетах.
    assert recall_at_k(["x"], [], k=5) == 1.0


def test_metrics_aggregates_zero_for_empty_dataset():
    from evals.metrics import aggregate_reports

    report = aggregate_reports([], k=5)
    assert report.total == 0
    assert report.precision_at_1 == 0.0
    assert report.recall_at_5 == 0.0
    assert report.mrr == 0.0


def test_dataset_loader_rejects_missing_query(tmp_path):
    from evals.dataset import load_dataset

    bad = tmp_path / "bad.yaml"
    bad.write_text("cases:\n  - expected_titles: ['x']\n", encoding="utf-8")
    with pytest.raises(ValueError, match="query"):
        load_dataset(bad)


def test_dataset_loader_rejects_empty_titles(tmp_path):
    from evals.dataset import load_dataset

    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "cases:\n  - query: 'x'\n    expected_titles: []\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="expected_titles"):
        load_dataset(bad)


def test_dataset_loader_normalizes_titles(tmp_path):
    from evals.dataset import load_dataset

    src = tmp_path / "ok.yaml"
    src.write_text(
        "cases:\n"
        "  - query: 'q'\n"
        "    expected_titles:\n"
        "      - '  Сброс  Пароля  '\n",
        encoding="utf-8",
    )
    cases = load_dataset(src)
    # «  Сброс  Пароля  » должно нормализоваться в «сброс пароля» — этот же
    # формат используется в pytest при сравнении с title'ами из БД.
    assert "сброс пароля" in cases[0].expected_titles
