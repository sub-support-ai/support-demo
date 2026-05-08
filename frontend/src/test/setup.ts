// Автозагружается Vitest перед каждым тест-файлом (см. vitest.config.ts).
//
// 1) jest-dom — расширяет expect матчерами вроде toBeInTheDocument(),
//    toHaveTextContent() и т.п. Без них тесты на компоненты были бы
//    многословными.
// 2) afterEach(cleanup) — RTL не делает cleanup сам в Vitest (в Jest это
//    было автоматически), поэтому между тестами компоненты бы оставались
//    смонтированными и портили счётчики.

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
