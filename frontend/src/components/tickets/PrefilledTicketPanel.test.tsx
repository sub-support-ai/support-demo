/**
 * PrefilledTicketPanel component tests.
 *
 * Покрывает:
 *   - Badge отдела использует getDepartmentLabel (русский, не сырое значение)
 *   - Кнопка «Отправить» disabled при пустых обязательных полях
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
        onDecline={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    expect(screen.getAllByText("ИТ").length).toBeGreaterThan(0);
  });

  it("показывает 'АХО' для department='facilities'", () => {
    renderWithProviders(
      <PrefilledTicketPanel
        ticket={makeDraftTicket({ department: "facilities" })}
        onConfirm={vi.fn()}
        onDecline={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    expect(screen.getAllByText("АХО").length).toBeGreaterThan(0);
  });
});

describe("PrefilledTicketPanel — кнопка «Отправить»", () => {
  it("кнопка активна если все обязательные поля заполнены", () => {
    renderWithProviders(
      <PrefilledTicketPanel
        ticket={makeDraftTicket()}
        onConfirm={vi.fn()}
        onDecline={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    const btn = screen.getByRole("button", { name: /^Отправить$/i });
    expect(btn).not.toBeDisabled();
  });

  it("кнопка disabled если requester_name пустой", () => {
    renderWithProviders(
      <PrefilledTicketPanel
        ticket={makeDraftTicket({ requester_name: "" })}
        onConfirm={vi.fn()}
        onDecline={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    const btn = screen.getByRole("button", { name: /^Отправить$/i });
    expect(btn).toBeDisabled();
  });

  it("кнопка disabled если office пустой", () => {
    renderWithProviders(
      <PrefilledTicketPanel
        ticket={makeDraftTicket({ office: "" })}
        onConfirm={vi.fn()}
        onDecline={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    const btn = screen.getByRole("button", { name: /^Отправить$/i });
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
        onDecline={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /Изменить/i })).not.toBeInTheDocument();
  });
});

describe("PrefilledTicketPanel — предупреждение о дубликатах", () => {
  // Минимальный фабричный тикет для «уже открытого похожего».
  function makeDuplicateTicket(overrides: Partial<Ticket> = {}): Ticket {
    return {
      id: 99,
      user_id: 5,
      title: "Похожий открытый тикет",
      body: "...",
      user_priority: 3,
      status: "in_progress",
      department: "IT",
      ticket_source: "chat",
      confirmed_by_user: true,
      created_at: new Date().toISOString(),
      ...overrides,
    };
  }

  it("показывает Alert если потенциальные дубликаты переданы", () => {
    renderWithProviders(
      <PrefilledTicketPanel
        ticket={makeDraftTicket()}
        potentialDuplicates={[makeDuplicateTicket({ id: 42, title: "Старый VPN-запрос" })]}
        onConfirm={vi.fn()}
        onDecline={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    expect(screen.getByText(/Похожий запрос уже открыт/i)).toBeInTheDocument();
    // Содержит ID и заголовок дубликата
    expect(screen.getByText(/#42/)).toBeInTheDocument();
    expect(screen.getByText(/Старый VPN-запрос/)).toBeInTheDocument();
  });

  it("показывает множественное число если дубликатов больше одного", () => {
    renderWithProviders(
      <PrefilledTicketPanel
        ticket={makeDraftTicket()}
        potentialDuplicates={[
          makeDuplicateTicket({ id: 41 }),
          makeDuplicateTicket({ id: 42 }),
        ]}
        onConfirm={vi.fn()}
        onDecline={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    expect(screen.getByText(/Похожих запросов открыто: 2/i)).toBeInTheDocument();
  });

  it("обрезает список после 3 дубликатов и показывает «и ещё N»", () => {
    const dupes = Array.from({ length: 5 }, (_, i) =>
      makeDuplicateTicket({ id: 100 + i, title: `Тикет ${i}` }),
    );
    renderWithProviders(
      <PrefilledTicketPanel
        ticket={makeDraftTicket()}
        potentialDuplicates={dupes}
        onConfirm={vi.fn()}
        onDecline={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    expect(screen.getByText(/и ещё 2/i)).toBeInTheDocument();
  });

  it("не показывает Alert если массив пуст", () => {
    renderWithProviders(
      <PrefilledTicketPanel
        ticket={makeDraftTicket()}
        potentialDuplicates={[]}
        onConfirm={vi.fn()}
        onDecline={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    expect(screen.queryByText(/Похожий запрос уже открыт/i)).not.toBeInTheDocument();
  });

  it("не показывает Alert если тикет уже подтверждён (canEdit=false)", () => {
    // После подтверждения пользователь уже не может ничего изменить —
    // предупреждение бесполезно и только зашумляет.
    renderWithProviders(
      <PrefilledTicketPanel
        ticket={makeDraftTicket({ confirmed_by_user: true, status: "confirmed" })}
        potentialDuplicates={[makeDuplicateTicket({ id: 42 })]}
        onConfirm={vi.fn()}
        onDecline={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    expect(screen.queryByText(/Похожий запрос уже открыт/i)).not.toBeInTheDocument();
  });
});
