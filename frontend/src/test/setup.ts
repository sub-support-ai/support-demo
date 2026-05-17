// Автозагружается Vitest перед каждым тест-файлом (см. vitest.config.ts).
//
// 1) jest-dom — расширяет expect матчерами вроде toBeInTheDocument(),
//    toHaveTextContent() и т.п. Без них тесты на компоненты были бы
//    многословными.
// 2) afterEach(cleanup) — RTL не делает cleanup сам в Vitest (в Jest это
//    было автоматически), поэтому между тестами компоненты бы оставались
//    смонтированными и портили счётчики.
// 3) window.matchMedia mock — jsdom не реализует matchMedia. Mantine использует
//    его для определения color scheme и media queries. Без мока все компонентные
//    тесты падают с "TypeError: window.matchMedia is not a function".

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});

// ResizeObserver — нужен Mantine Textarea с autosize и ScrollArea.
// jsdom его не реализует, заглушка с пустыми методами достаточна.
class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
Object.defineProperty(window, "ResizeObserver", {
  writable: true,
  value: ResizeObserverMock,
});

// Mantine использует window.matchMedia для определения color scheme
// и responsive breakpoints. jsdom не реализует этот API.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});
