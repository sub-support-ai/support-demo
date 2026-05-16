/**
 * Тесты sla.ts. Логика дат хрупкая, ошибки в форматтерах легко проскакивают
 * через ревью. Поэтому здесь — таблично, с явным `now` для детерминизма.
 *
 * Все тесты используют фиксированный «сейчас» — 2026-05-15 12:00 (пятница),
 * который удобен потому что:
 *   - середина недели и месяца (нет крайних случаев типа конца месяца)
 *   - пятница позволяет проверить переход через выходные
 */

import { describe, expect, it } from "vitest";

import {
  formatFriendlyDeadline,
  formatOperatorDeadline,
  getDeadlineColor,
  getDeadlineStatus,
} from "./sla";

const NOW = new Date("2026-05-15T12:00:00Z"); // пятница, 12:00 UTC

describe("getDeadlineStatus", () => {
  it("возвращает null если значение пустое или невалидное", () => {
    expect(getDeadlineStatus(null)).toBeNull();
    expect(getDeadlineStatus(undefined)).toBeNull();
    expect(getDeadlineStatus("")).toBeNull();
    expect(getDeadlineStatus("not-a-date")).toBeNull();
  });

  it("breached если SLA уже просрочен по времени", () => {
    const past = new Date(NOW.getTime() - 60_000).toISOString();
    expect(getDeadlineStatus(past, { now: NOW })).toBe("breached");
  });

  it("breached если is_sla_breached=true, даже если по времени ещё ОК", () => {
    const future = new Date(NOW.getTime() + 24 * 3_600_000).toISOString();
    expect(getDeadlineStatus(future, { breached: true, now: NOW })).toBe("breached");
  });

  it("urgent если осталось < 2 часов", () => {
    const oneHour = new Date(NOW.getTime() + 3_600_000).toISOString();
    expect(getDeadlineStatus(oneHour, { now: NOW })).toBe("urgent");
  });

  it("warning если осталось 2-8 часов", () => {
    const fourHours = new Date(NOW.getTime() + 4 * 3_600_000).toISOString();
    expect(getDeadlineStatus(fourHours, { now: NOW })).toBe("warning");
  });

  it("ok если больше 8 часов", () => {
    const oneDay = new Date(NOW.getTime() + 24 * 3_600_000).toISOString();
    expect(getDeadlineStatus(oneDay, { now: NOW })).toBe("ok");
  });
});

describe("getDeadlineColor", () => {
  it.each([
    ["breached", "red"],
    ["urgent", "orange"],
    ["warning", "yellow"],
    ["ok", "teal"],
  ] as const)("%s → %s", (status, expected) => {
    expect(getDeadlineColor(status)).toBe(expected);
  });
});

describe("formatFriendlyDeadline", () => {
  it("возвращает null если значение пустое или невалидное", () => {
    expect(formatFriendlyDeadline(null)).toBeNull();
    expect(formatFriendlyDeadline(undefined)).toBeNull();
    expect(formatFriendlyDeadline("garbage")).toBeNull();
  });

  it("«истёк срок ответа» если SLA просрочен", () => {
    const past = new Date(NOW.getTime() - 60_000).toISOString();
    expect(formatFriendlyDeadline(past, { now: NOW })).toBe("истёк срок ответа");
  });

  it("«истёк срок ответа» если is_sla_breached=true", () => {
    const future = new Date(NOW.getTime() + 24 * 3_600_000).toISOString();
    expect(formatFriendlyDeadline(future, { breached: true, now: NOW })).toBe(
      "истёк срок ответа",
    );
  });

  it("«до HH:MM сегодня» если дедлайн до полуночи сегодня", () => {
    // +3 часа от 12:00 = 15:00 того же дня
    const today15 = new Date(NOW.getTime() + 3 * 3_600_000).toISOString();
    const result = formatFriendlyDeadline(today15, { now: NOW });
    expect(result).toMatch(/^до \d{2}:\d{2} сегодня$/);
    expect(result).toContain("сегодня");
  });

  it("«до HH:MM завтра» если дедлайн на следующий день", () => {
    const tomorrow = new Date(NOW.getTime() + 24 * 3_600_000).toISOString();
    const result = formatFriendlyDeadline(tomorrow, { now: NOW });
    expect(result).toMatch(/^до \d{2}:\d{2} завтра$/);
  });

  it("«до HH:MM в <день>» если дедлайн через 2-6 дней", () => {
    // +3 дня от пятницы = понедельник
    const inThreeDays = new Date(NOW.getTime() + 3 * 24 * 3_600_000).toISOString();
    const result = formatFriendlyDeadline(inThreeDays, { now: NOW });
    // должно содержать день недели (понедельник)
    expect(result).toMatch(/^до \d{2}:\d{2} в /);
    expect(result).toContain("понедельник");
  });

  it("«до HH:MM, DD.MM» если дедлайн через неделю или больше", () => {
    const inTenDays = new Date(NOW.getTime() + 10 * 24 * 3_600_000).toISOString();
    const result = formatFriendlyDeadline(inTenDays, { now: NOW });
    expect(result).toMatch(/^до \d{2}:\d{2}, \d{2}\.\d{2}$/);
  });
});

describe("formatOperatorDeadline", () => {
  it("возвращает null если значения нет", () => {
    expect(formatOperatorDeadline(null)).toBeNull();
    expect(formatOperatorDeadline(undefined)).toBeNull();
  });

  it("«просрочен N ч M мин» если SLA нарушен", () => {
    // 2 часа 15 минут назад
    const past = new Date(NOW.getTime() - (2 * 3_600_000 + 15 * 60_000)).toISOString();
    expect(formatOperatorDeadline(past, { now: NOW })).toBe("просрочен 2 ч 15 мин");
  });

  it("«просрочен N мин» если меньше часа просрочки", () => {
    const past = new Date(NOW.getTime() - 30 * 60_000).toISOString();
    expect(formatOperatorDeadline(past, { now: NOW })).toBe("просрочен 30 мин");
  });

  it("«N мин до дедлайна» если < 2 часов", () => {
    const inHalfHour = new Date(NOW.getTime() + 30 * 60_000).toISOString();
    expect(formatOperatorDeadline(inHalfHour, { now: NOW })).toBe("30 мин до дедлайна");
  });

  it("«N ч до дедлайна» если 2-8 часов", () => {
    const inFiveHours = new Date(NOW.getTime() + 5 * 3_600_000).toISOString();
    expect(formatOperatorDeadline(inFiveHours, { now: NOW })).toBe("5 ч до дедлайна");
  });

  it("null если больше 8 часов — оператора не беспокоим, времени достаточно", () => {
    const inOneDay = new Date(NOW.getTime() + 24 * 3_600_000).toISOString();
    expect(formatOperatorDeadline(inOneDay, { now: NOW })).toBeNull();
  });

  it("respects breached флаг даже при положительном diff", () => {
    const future = new Date(NOW.getTime() + 24 * 3_600_000).toISOString();
    const result = formatOperatorDeadline(future, { breached: true, now: NOW });
    expect(result).toMatch(/^просрочен/);
  });
});
