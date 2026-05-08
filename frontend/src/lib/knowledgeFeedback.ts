// Хелперы для отображения «полезности» статьи KB в админке.
//
// Вынесены отдельно от KnowledgePage.tsx, чтобы их можно было покрыть
// юнит-тестами без таскания Mantine + React Query (см. tests/knowledgeFeedback.test.ts).
//
// Контракт цветов (зелёный/жёлтый/красный) — на скриншоте админки сразу
// видны слабые статьи. Менять пороги — менять и тесты.

import type { KnowledgeArticle } from "../api/types";

export type FeedbackStats = {
  total: number;
  helpedRatio: number; // 0..1, NaN если total==0
};

export function summarizeFeedback(
  article: Pick<
    KnowledgeArticle,
    "helped_count" | "not_helped_count" | "not_relevant_count"
  >,
): FeedbackStats {
  const total =
    article.helped_count + article.not_helped_count + article.not_relevant_count;
  return {
    total,
    helpedRatio: total === 0 ? Number.NaN : article.helped_count / total,
  };
}

export function feedbackBadgeColor(ratio: number, total: number): string {
  if (total === 0) return "gray";
  if (ratio >= 0.7) return "green";
  if (ratio >= 0.4) return "yellow";
  return "red";
}
