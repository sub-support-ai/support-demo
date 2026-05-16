/**
 * Тесты CSV-экспорта. Покрываем эскейпинг (легко допустить ошибку
 * и испортить файл при значениях с кавычками или переносами) и
 * структуру выходной строки.
 *
 * Реальный download (downloadTicketsCsv) не тестируем — он только
 * обёртка над DOM API; вся логика — в чистых ticketsToCsv/escapeCsvCell.
 */

import { describe, expect, it } from "vitest";

import type { Ticket } from "../api/types";
import { escapeCsvCell, ticketsToCsv, TICKET_CSV_COLUMNS, toCsv } from "./csv";

function makeTicket(overrides: Partial<Ticket> = {}): Ticket {
  return {
    id: 1,
    user_id: 10,
    title: "Тестовый тикет",
    body: "Тело тикета",
    user_priority: 3,
    status: "confirmed",
    department: "IT",
    ticket_source: "manual",
    confirmed_by_user: true,
    created_at: "2026-05-15T10:00:00Z",
    ...overrides,
  } as Ticket;
}

describe("escapeCsvCell", () => {
  it("возвращает пустую строку для null/undefined", () => {
    expect(escapeCsvCell(null)).toBe("");
    expect(escapeCsvCell(undefined)).toBe("");
  });

  it("числа конвертируются в строку без экранирования", () => {
    expect(escapeCsvCell(42)).toBe("42");
    expect(escapeCsvCell(0)).toBe("0");
  });

  it("обычная строка возвращается как есть", () => {
    expect(escapeCsvCell("привет")).toBe("привет");
  });

  it("оборачивает в кавычки если есть `;`", () => {
    expect(escapeCsvCell("a;b")).toBe('"a;b"');
  });

  it("оборачивает в кавычки и экранирует внутренние кавычки", () => {
    expect(escapeCsvCell('он сказал "стоп"')).toBe('"он сказал ""стоп"""');
  });

  it("оборачивает в кавычки при переносе строки", () => {
    expect(escapeCsvCell("первая\nвторая")).toBe('"первая\nвторая"');
    expect(escapeCsvCell("первая\r\nвторая")).toBe('"первая\r\nвторая"');
  });
});

describe("ticketsToCsv", () => {
  it("для пустого списка возвращает только заголовок", () => {
    const result = ticketsToCsv([]);
    const lines = result.split("\r\n");
    expect(lines).toHaveLength(1);
    expect(lines[0]).toContain("ID");
    expect(lines[0]).toContain("Тема");
    expect(lines[0]).toContain("Отдел");
  });

  it("кириллица в значениях сохраняется как есть (BOM добавляется при скачивании)", () => {
    const csv = ticketsToCsv([makeTicket({ title: "Не работает VPN" })]);
    expect(csv).toContain("Не работает VPN");
  });

  it("заголовок отделён от данных через CRLF", () => {
    const csv = ticketsToCsv([makeTicket()]);
    expect(csv.split("\r\n")).toHaveLength(2); // header + 1 row
  });

  it("отдел переводится через getDepartmentLabel", () => {
    // department='IT' должно отобразиться как 'ИТ', не сырое 'IT'
    const csv = ticketsToCsv([makeTicket({ department: "IT" })]);
    expect(csv).toContain("ИТ");
  });

  it("статус переводится через getStatusLabel", () => {
    const csv = ticketsToCsv([makeTicket({ status: "in_progress" })]);
    expect(csv).toContain("В работе");
  });

  it("SLA нарушен → 'да', иначе 'нет'", () => {
    const breached = ticketsToCsv([makeTicket({ is_sla_breached: true })]);
    const normal = ticketsToCsv([makeTicket({ is_sla_breached: false })]);
    expect(breached.split("\r\n")[1]).toContain(";да;");
    expect(normal.split("\r\n")[1]).toContain(";нет;");
  });

  it("значение с `;` оборачивается в кавычки", () => {
    const csv = ticketsToCsv([makeTicket({ title: "тема; с точкой запятой" })]);
    expect(csv).toContain('"тема; с точкой запятой"');
  });

  it("null поля становятся пустыми ячейками", () => {
    const csv = ticketsToCsv([
      makeTicket({
        requester_email: null,
        office: null,
        sla_deadline_at: null,
      }),
    ]);
    // ;;; означает пустые ячейки подряд
    expect(csv).toMatch(/;;;/);
  });

  it("несколько тикетов → несколько строк после заголовка", () => {
    const csv = ticketsToCsv([
      makeTicket({ id: 1 }),
      makeTicket({ id: 2 }),
      makeTicket({ id: 3 }),
    ]);
    expect(csv.split("\r\n")).toHaveLength(4); // header + 3 rows
  });
});

describe("toCsv (общий)", () => {
  it("работает с произвольным типом", () => {
    const items = [{ a: 1, b: "x" }];
    const csv = toCsv(items, [
      { label: "A", value: (i) => i.a },
      { label: "B", value: (i) => i.b },
    ]);
    expect(csv).toBe("A;B\r\n1;x");
  });
});

describe("TICKET_CSV_COLUMNS", () => {
  it("содержит критические колонки", () => {
    const labels = TICKET_CSV_COLUMNS.map((c) => c.label);
    expect(labels).toContain("ID");
    expect(labels).toContain("Тема");
    expect(labels).toContain("Отдел");
    expect(labels).toContain("Статус");
    expect(labels).toContain("Приоритет");
    expect(labels).toContain("SLA дедлайн");
  });
});
