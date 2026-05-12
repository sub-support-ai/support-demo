/**
 * PrefilledTicketPanel component tests.
 *
 * Покрывает:
 *   - Badge отдела использует getDepartmentLabel (русский, не сырое значение)
 *   - Кнопка «Отправить как есть» disabled при пустых обязательных полях
 *   - Компонент рендерится без ошибок в разных состояниях
 */

import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Ticket } from "../../api/types";
import { renderWithProviders } from "../../test/renderWithProviders";
import { PrefilledTicketPanel } from "./PrefilledTicketPanel";

function makeDraftTicket(overrides: Partial<Ticket> = {}): Ticket {
  return {
    id: 2,
    user_id: 5,
    title: "Нет доступа к системе",
    body: "Не могу войти в корпоративную почту.",
    user_priority: 3,
    status: "pending_user",
    department: "IT",
    ticket_source: "chat",
    confirmed_by_user: false,
    requester_name: "Иван Иванов",
    requester_email: "ivan@example.com",
    office: "Офис А",
    affected_item: "Корпоративная почта",
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("PrefilledTicketPanel — department badge", () => {
  it("показывает 'ИТ' для department='IT'", () => {
    renderWithProviders(
      <PrefilledTicketPanel
        ticket={makeDraftTicket({ department: "IT" })}
        onConfirm={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    expect(screen.getByText("ИТ")).toBeInTheDocument();
  });

  it("показывает 'АХО' для department='facilities'", () => {
    renderWithProviders(
      <PrefilledTicketPanel
        ticket={makeDraftTicket({ department: "facilities" })}
        onConfirm={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    expect(screen.getByText("АХО")).toBeInTheDocument();
  });
});

describe("PrefilledTicketPanel — кнопка «Отправить»", () => {
  it("кнопка активна если все обязательные поля заполнены", () => {
    renderWithProviders(
      <PrefilledTicketPanel
        ticket={makeDraftTicket()}
        onConfirm={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    const btn = screen.getByRole("button", { name: /Отправить как есть/i });
    expect(btn).not.toBeDisabled();
  });

  it("кнопка disabled если requester_name пустой", () => {
    renderWithProviders(
      <PrefilledTicketPanel
        ticket={makeDraftTicket({ requester_name: "" })}
        onConfirm={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    const btn = screen.getByRole("button", { name: /Отправить как есть/i });
    expect(btn).toBeDisabled();
  });

  it("кнопка disabled если office пустой", () => {
    renderWithProviders(
      <PrefilledTicketPanel
        ticket={makeDraftTicket({ office: "" })}
        onConfirm={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    const btn = screen.getByRole("button", { name: /Отправить как есть/i });
    expect(btn).toBeDisabled();
  });
});

describe("PrefilledTicketPanel — состояние confirmed", () => {
  it("кнопка «Изменить» не отображается если тикет уже подтверждён (canEdit=false)", () => {
    // canEdit = !confirmed_by_user && status === "pending_user"
    // При confirmed_by_user=true редактирование недоступно.
    renderWithProviders(
      <PrefilledTicketPanel
        ticket={makeDraftTicket({ confirmed_by_user: true, status: "open" })}
        onConfirm={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /Изменить/i })).not.toBeInTheDocument();
  });
});
