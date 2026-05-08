// Тесты на «полезность» статьи в админке.
// Эти числа уезжают в production-дашборд (зелёный/жёлтый/красный бейдж),
// поэтому пороги фиксируем явно — любая правка thresholds должна
// сопровождаться правкой теста.

import { describe, expect, it } from "vitest";

import { feedbackBadgeColor, summarizeFeedback } from "./knowledgeFeedback";

describe("summarizeFeedback", () => {
  it("returns NaN ratio when there are no feedbacks", () => {
    const stats = summarizeFeedback({
      helped_count: 0,
      not_helped_count: 0,
      not_relevant_count: 0,
    });
    expect(stats.total).toBe(0);
    expect(Number.isNaN(stats.helpedRatio)).toBe(true);
  });

  it("computes helped ratio over all three feedback kinds", () => {
    // 3 helped из 4 общих (1 not_helped, 0 not_relevant) → 0.75
    const stats = summarizeFeedback({
      helped_count: 3,
      not_helped_count: 1,
      not_relevant_count: 0,
    });
    expect(stats.total).toBe(4);
    expect(stats.helpedRatio).toBeCloseTo(0.75, 5);
  });

  it("counts not_relevant in the denominator (RAG misfire is still a signal)", () => {
    // Без not_relevant в total админ бы обвинил автора статьи — но проблема
    // у поиска, не у контента. Регрессия: ratio должен учитывать все три.
    const stats = summarizeFeedback({
      helped_count: 1,
      not_helped_count: 0,
      not_relevant_count: 1,
    });
    expect(stats.total).toBe(2);
    expect(stats.helpedRatio).toBeCloseTo(0.5, 5);
  });
});

describe("feedbackBadgeColor", () => {
  it("returns gray for empty stats", () => {
    expect(feedbackBadgeColor(Number.NaN, 0)).toBe("gray");
  });

  it("returns green at 70% helpful and above", () => {
    expect(feedbackBadgeColor(0.7, 10)).toBe("green");
    expect(feedbackBadgeColor(1.0, 10)).toBe("green");
  });

  it("returns yellow between 40% and 70%", () => {
    expect(feedbackBadgeColor(0.4, 10)).toBe("yellow");
    expect(feedbackBadgeColor(0.69, 10)).toBe("yellow");
  });

  it("returns red below 40%", () => {
    expect(feedbackBadgeColor(0.39, 10)).toBe("red");
    expect(feedbackBadgeColor(0.0, 10)).toBe("red");
  });
});
