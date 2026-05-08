// Конфиг Vitest для unit-/component-тестов.
//
// Принципы:
// - jsdom вместо node, потому что тесты могут потрогать DOM через RTL.
//   На чистых утилитах (lib/*) jsdom стоит почти ничего — пара мс на старте.
// - setupFiles подключают jest-dom matchers (toBeInTheDocument и т.п.)
//   и автоматический cleanup между тестами, чтобы DOM не утекал из теста в тест.
// - globals: false — оставляем явные импорты `describe / it / expect` для
//   чистоты autocomplete и чтобы линтеры не ругались на необъявленные имена.

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
