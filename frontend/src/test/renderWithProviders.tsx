/**
 * Вспомогательная функция для тестирования компонентов.
 *
 * Оборачивает компонент в обязательные провайдеры:
 *   - MantineProvider: Badge, Button, Text и другие компоненты Mantine
 *     бросают "MantineProvider was not found" без него.
 *   - QueryClientProvider: хуки useTicketComments, useResponseTemplates и др.
 *     требуют активного QueryClient.
 *
 * QueryClient создаётся заново для каждого вызова renderWithProviders —
 * тесты изолированы по данным кэша.
 *
 * Использование:
 *
 *   import { renderWithProviders } from "../../test/renderWithProviders";
 *
 *   renderWithProviders(<TicketCard ticket={ticket} currentUserRole="agent" />);
 *   expect(screen.getByText("ИТ")).toBeInTheDocument();
 */

import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions, type RenderResult } from "@testing-library/react";
import type { ReactNode } from "react";

function makeTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,      // мгновенное падение при ошибке — не 3 попытки
        staleTime: Infinity, // не стейлить данные между тестовыми renders
      },
    },
  });
}

function AllProviders({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={makeTestQueryClient()}>
      <MantineProvider>{children}</MantineProvider>
    </QueryClientProvider>
  );
}

export function renderWithProviders(
  ui: ReactNode,
  options?: Omit<RenderOptions, "wrapper">,
): RenderResult {
  return render(ui, { wrapper: AllProviders, ...options });
}
