// Frontend-валидация для форм входа/регистрации.
//
// Эти правила должны симметрировать backend: app/schemas/user.py.
// Если фронт пропускает то, что бэк отвергает — пользователь увидит
// внезапный 422 после нажатия Submit, а это самый раздражающий UX-провал.
// Любая правка backend-валидации обязана сопровождаться правкой и здесь,
// и в этом тестовом файле.

import { describe, expect, it } from "vitest";

import {
  hasValidationErrors,
  PASSWORD_MAX_LENGTH,
  validateAuthForm,
  validateEmail,
  validatePassword,
  validateUsername,
} from "./validation";

describe("validateEmail", () => {
  it("rejects empty input", () => {
    expect(validateEmail("")).toBe("Укажите email");
    expect(validateEmail("   ")).toBe("Укажите email");
  });

  it("rejects malformed addresses", () => {
    expect(validateEmail("not-an-email")).toBe("Введите корректный email");
    expect(validateEmail("missing@tld")).toBe("Введите корректный email");
    expect(validateEmail("@nouser.com")).toBe("Введите корректный email");
  });

  it("accepts a normal address", () => {
    expect(validateEmail("user@example.com")).toBeUndefined();
    expect(validateEmail("  user@example.com  ")).toBeUndefined();
  });

  it("guards against oversized input (DoS)", () => {
    // Backend режет email на стороне Pydantic; фронт должен отлавливать
    // 10kb-строку до отправки, иначе мы шлём в сеть гигабайт мусора при
    // copy-paste из чужого dump'а.
    const huge = `${"a".repeat(255)}@example.com`;
    expect(validateEmail(huge)).toBe("Email слишком длинный");
  });
});

describe("validatePassword", () => {
  it("rejects empty / too short / too long", () => {
    expect(validatePassword("")).toBe("Укажите пароль");
    expect(validatePassword("Aa1!")).toBe(
      "Пароль должен быть от 8 до 128 символов",
    );
    expect(validatePassword("A".repeat(PASSWORD_MAX_LENGTH + 1))).toBe(
      "Пароль должен быть от 8 до 128 символов",
    );
  });

  it("rejects whitespace inside password", () => {
    // Backend security.py отдельно режет пробелы — копируем то же правило,
    // чтобы пользователь не словил 422 после Submit.
    expect(validatePassword("Secret 123!")).toBe(
      "Пароль не должен содержать пробелы",
    );
  });

  it("requires lower / upper / digit / special character", () => {
    expect(validatePassword("SECRET123!")).toBe("Добавьте строчную букву");
    expect(validatePassword("secret123!")).toBe("Добавьте заглавную букву");
    expect(validatePassword("SecretSecret!")).toBe("Добавьте цифру");
    expect(validatePassword("Secret123A")).toBe("Добавьте спецсимвол");
  });

  it("accepts a password matching all rules", () => {
    expect(validatePassword("Secret123!")).toBeUndefined();
  });

  it("accepts cyrillic letters as lower/upper", () => {
    // Регрессия: были баги с тем, что регэксп принимал только ASCII.
    // Backend (security.py) хеширует через SHA-256 → bcrypt, поэтому
    // кириллический пароль валиден; фронту нельзя его блокировать.
    expect(validatePassword("Тест123!ы")).toBeUndefined();
  });
});

describe("validateUsername", () => {
  it("rejects empty after trim", () => {
    expect(validateUsername("   ")).toBe("Укажите логин");
  });

  it("accepts cyrillic and unicode usernames", () => {
    expect(validateUsername("юзер")).toBeUndefined();
    expect(validateUsername("user_42")).toBeUndefined();
  });
});

describe("validateAuthForm", () => {
  it("login mode skips email check and password complexity", () => {
    // На login достаточно непустого пароля — иначе пользователь не сможет
    // залогиниться со старым паролем, не отвечающим новой politik'е.
    const errors = validateAuthForm({
      mode: "login",
      email: "",
      username: "user",
      password: "old", // короткий, без спецсимволов — но это уже их пароль
    });
    expect(errors.email).toBeUndefined();
    expect(errors.username).toBeUndefined();
    expect(errors.password).toBeUndefined();
    expect(hasValidationErrors(errors)).toBe(false);
  });

  it("register mode validates all three fields", () => {
    const errors = validateAuthForm({
      mode: "register",
      email: "bad",
      username: "",
      password: "weak",
    });
    expect(errors.email).toBeDefined();
    expect(errors.username).toBeDefined();
    expect(errors.password).toBeDefined();
    expect(hasValidationErrors(errors)).toBe(true);
  });

  it("login flags missing password explicitly", () => {
    const errors = validateAuthForm({
      mode: "login",
      email: "",
      username: "user",
      password: "",
    });
    expect(errors.password).toBe("Укажите пароль");
  });
});
