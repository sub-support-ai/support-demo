/**
 * Тесты утилит getDepartmentLabel — регрессия на все 7 отделов.
 *
 * Эти тесты важны потому что getDepartmentLabel используется в TicketCard,
 * PrefilledTicketPanel и других компонентах. Ошибка здесь распространится
 * везде, где используется эта функция.
 */

import { describe, expect, it } from "vitest";
import { getDepartmentLabel } from "./ticketLabels";

describe("getDepartmentLabel", () => {
  it.each([
    ["IT", "ИТ"],
    ["HR", "Кадры"],
    ["finance", "Финансы"],
    ["procurement", "Закупки"],
    ["security", "Безопасность"],
    ["facilities", "АХО"],
    ["documents", "Документооборот"],
  ] as const)("department='%s' → '%s'", (input, expected) => {
    expect(getDepartmentLabel(input)).toBe(expected);
  });

  it("возвращает 'Без отдела' для undefined", () => {
    expect(getDepartmentLabel(undefined)).toBe("Без отдела");
  });

  it("возвращает 'Без отдела' для null", () => {
    expect(getDepartmentLabel(null)).toBe("Без отдела");
  });

  it("возвращает исходное значение для неизвестного отдела (fallback)", () => {
    expect(getDepartmentLabel("unknown_dept")).toBe("unknown_dept");
  });
});
