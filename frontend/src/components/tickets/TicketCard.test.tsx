/**
 * TicketCard component tests.
 *
 * Регрессионное покрытие:
 *   - getDepartmentLabel применяется перед рендером badge.
 *     "IT" должно отображаться как "ИТ", не как raw-значение.
 *     Класс бага, который уже был в проде.
 *   - Все 7 отделов корректно транслируются.
 *   - Пользовательская роль скрывает операторские контролы.
 */

import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Ticket } from "../../api/types";
import { renderWithProviders } from "../../test/renderWithProviders";
import { TicketCard } from "./TicketCard";

// TicketCard использует несколько React Query хуков для загрузки данных.
// Мокируем их на уровне модуля — нас интересует только рендер, не данные.
vi.mock("../../api/tickets", () => ({
  useTicketComments: () => ({ data: [], isLoading: false, error: null }),
  useCreateTicketComment: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateTicketStatus: () => ({ mutate: vi.fn(), isPending: false }),
  useResolveTicket: () => ({ mutate: vi.fn(), isPending: false }),
  useSubmitTicketFeedback: () => ({ mutate: vi.fn(), isPending: false }),
  usePromoteTicketToKb: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock("../../api/responseTemplates", () => ({
  useResponseTemplates: () => ({ data: [], isLoading: false }),
}));

function makeTicket(overrides: Partial<Ticket> = {}): Ticket {
  return {
    id: 1,
    user_id: 10,
    title: "Тестовый тикет",
    body: "Описание проблемы.",
    user_priority: 3,
    status: "new",
    department: "IT",
    ticket_source: "chat",
    confirmed_by_user: false,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("TicketCard — department badge", () => {
  it("показывает 'ИТ' для department='IT', не сырое значение", () => {
    renderWithProviders(
      <TicketCard ticket={makeTicket({ department: "IT" })} currentUserRole="agent" />,
    );
    expect(screen.getByText("ИТ")).toBeInTheDocument();
    // Сырое значение "IT" не должно быть в badge-тексте
    // (может присутствовать в других местах, поэтому не используем queryByText)
  });

  it.each([
    ["HR", "Кадры"],
    ["finance", "Финансы"],
    ["procurement", "Закупки"],
    ["security", "Безопасность"],
    ["facilities", "АХО"],
    ["documents", "Документооборот"],
  ] as const)(
    "department='%s' рендерится как '%s'",
    (department, expectedLabel) => {
      renderWithProviders(
        <TicketCard ticket={makeTicket({ department })} currentUserRole="agent" />,
      );
      expect(screen.getByText(expectedLabel)).toBeInTheDocument();
    },
  );
});

describe("TicketCard — содержимое", () => {
  it("показывает заголовок и тело тикета", () => {
    const ticket = makeTicket({
      title: "Принтер не печатает",
      body: "Уже три дня без печати.",
    });
    renderWithProviders(<TicketCard ticket={ticket} currentUserRole="agent" />);
    expect(screen.getByText("Принтер не печатает")).toBeInTheDocument();
    expect(screen.getByText("Уже три дня без печати.")).toBeInTheDocument();
  });
});

describe("TicketCard — роли", () => {
  it("пользовательская роль не видит кнопку закрытия тикета", () => {
    renderWithProviders(
      <TicketCard
        ticket={makeTicket({ status: "in_progress", confirmed_by_user: true })}
        currentUserRole="user"
      />,
    );
    // Кнопка «Решено» — только для агентов
    expect(screen.queryByText("Решено")).not.toBeInTheDocument();
  });
});
