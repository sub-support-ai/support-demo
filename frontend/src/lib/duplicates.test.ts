/**
 * Тесты findPotentialDuplicates.
 *
 * Алгоритм критичен для UX: ложноположительные срабатывания будут раздражать
 * («постоянно говорит мне про дубликаты, а это разные проблемы»),
 * ложноотрицательные — приведут к плодящимся тикетам. Поэтому стараемся
 * покрыть все ключевые условия матча.
 */

import { describe, expect, it } from "vitest";

import type { Ticket } from "../api/types";
import { findPotentialDuplicates } from "./duplicates";

function makeTicket(overrides: Partial<Ticket> = {}): Ticket {
  return {
    id: 1,
    user_id: 10,
    title: "Тикет",
    body: "Тело",
    user_priority: 3,
    status: "confirmed",
    department: "IT",
    ticket_source: "manual",
    confirmed_by_user: true,
    affected_item: "VPN",
    request_type: "доступ",
    created_at: "2026-05-15T10:00:00Z",
    ...overrides,
  } as Ticket;
}

describe("findPotentialDuplicates", () => {
  it("возвращает пустой массив если allTickets пуст", () => {
    const draft = makeTicket();
    expect(findPotentialDuplicates(draft, [])).toEqual([]);
  });

  it("не считает сам тикет дубликатом самого себя", () => {
    const draft = makeTicket({ id: 1 });
    expect(findPotentialDuplicates(draft, [draft])).toEqual([]);
  });

  it("находит дубликат по совпадению affected_item", () => {
    const draft = makeTicket({ id: 1, affected_item: "VPN" });
    const other = makeTicket({ id: 2, affected_item: "VPN" });
    expect(findPotentialDuplicates(draft, [other])).toEqual([other]);
  });

  it("находит дубликат по department + request_type", () => {
    const draft = makeTicket({
      id: 1,
      department: "IT",
      request_type: "пароль",
      affected_item: null,
    });
    const other = makeTicket({
      id: 2,
      department: "IT",
      request_type: "пароль",
      affected_item: null,
    });
    expect(findPotentialDuplicates(draft, [other])).toEqual([other]);
  });

  it("матч case-insensitive с trim", () => {
    const draft = makeTicket({ id: 1, affected_item: "  Vpn " });
    const other = makeTicket({ id: 2, affected_item: "vpn" });
    expect(findPotentialDuplicates(draft, [other])).toHaveLength(1);
  });

  it("не матчит чужие тикеты (другой user_id)", () => {
    const draft = makeTicket({ id: 1, user_id: 10 });
    const other = makeTicket({ id: 2, user_id: 11 }); // другой пользователь
    expect(findPotentialDuplicates(draft, [other])).toEqual([]);
  });

  it("не матчит закрытые тикеты", () => {
    const draft = makeTicket({ id: 1, status: "pending_user" });
    const closed = makeTicket({ id: 2, status: "closed" });
    const resolved = makeTicket({ id: 3, status: "resolved" });
    const declined = makeTicket({ id: 4, status: "declined" });
    expect(findPotentialDuplicates(draft, [closed, resolved, declined])).toEqual([]);
  });

  it("матчит open-статусы: pending_user, confirmed, in_progress, ai_processing", () => {
    const draft = makeTicket({ id: 1, affected_item: "VPN" });
    const tickets = [
      makeTicket({ id: 2, status: "pending_user", affected_item: "VPN" }),
      makeTicket({ id: 3, status: "confirmed", affected_item: "VPN" }),
      makeTicket({ id: 4, status: "in_progress", affected_item: "VPN" }),
      makeTicket({ id: 5, status: "ai_processing", affected_item: "VPN" }),
    ];
    expect(findPotentialDuplicates(draft, tickets)).toHaveLength(4);
  });

  it("возвращает пустой массив если у черновика нет ни affected_item, ни request_type", () => {
    const draft = makeTicket({
      id: 1,
      affected_item: null,
      request_type: null,
    });
    const other = makeTicket({ id: 2, affected_item: null });
    expect(findPotentialDuplicates(draft, [other])).toEqual([]);
  });

  it("не матчит по affected_item если в other он пустой", () => {
    // Защита от ложного срабатывания: пустой ↔ пустой не считается совпадением,
    // даже если другие проверки прошли.
    const draft = makeTicket({ id: 1, affected_item: "VPN", request_type: "доступ" });
    const other = makeTicket({
      id: 2,
      affected_item: null,
      request_type: "другой тип",
    });
    expect(findPotentialDuplicates(draft, [other])).toEqual([]);
  });

  it("не матчит по только department без request_type", () => {
    // Без request_type один отдел — это слишком широко (вся очередь ИТ).
    const draft = makeTicket({
      id: 1,
      department: "IT",
      request_type: null,
      affected_item: null,
    });
    const other = makeTicket({
      id: 2,
      department: "IT",
      request_type: "пароль",
      affected_item: null,
    });
    expect(findPotentialDuplicates(draft, [other])).toEqual([]);
  });

  it("возвращает несколько дубликатов если их больше одного", () => {
    const draft = makeTicket({
      id: 1,
      affected_item: "VPN",
      department: "IT",
      request_type: "доступ",
    });
    const dupes = [
      // Матчатся по affected_item
      makeTicket({ id: 2, affected_item: "VPN", department: "HR", request_type: "другое" }),
      makeTicket({ id: 3, affected_item: "VPN", department: "HR", request_type: "другое" }),
    ];
    // Полностью несвязанный: другой affected_item И другая связка отдел+тип
    const unrelated = makeTicket({
      id: 4,
      affected_item: "Принтер",
      department: "HR",
      request_type: "новый сотрудник",
    });
    expect(findPotentialDuplicates(draft, [...dupes, unrelated])).toHaveLength(2);
  });
});
