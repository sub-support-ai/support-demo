export const USERNAME_MAX_LENGTH = 100;
export const PASSWORD_MIN_LENGTH = 8;
export const PASSWORD_MAX_LENGTH = 128;

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export interface AuthValidationErrors {
  email?: string;
  username?: string;
  password?: string;
}

export function validateEmail(email: string): string | undefined {
  const value = email.trim();
  if (!value) {
    return "Укажите email";
  }
  if (value.length > 254) {
    return "Email слишком длинный";
  }
  if (!EMAIL_RE.test(value)) {
    return "Введите корректный email";
  }
  return undefined;
}

export function validateUsername(username: string): string | undefined {
  const value = username.trim();
  if (!value) {
    return "Укажите логин";
  }
  if (value.length > USERNAME_MAX_LENGTH) {
    return "Логин слишком длинный";
  }
  return undefined;
}

export function validatePassword(password: string): string | undefined {
  if (!password) {
    return "Укажите пароль";
  }
  if (
    password.length < PASSWORD_MIN_LENGTH ||
    password.length > PASSWORD_MAX_LENGTH
  ) {
    return "Пароль должен быть от 8 до 128 символов";
  }
  if (/\s/.test(password)) {
    return "Пароль не должен содержать пробелы";
  }
  if (!/[a-zа-яё]/.test(password)) {
    return "Добавьте строчную букву";
  }
  if (!/[A-ZА-ЯЁ]/.test(password)) {
    return "Добавьте заглавную букву";
  }
  if (!/\d/.test(password)) {
    return "Добавьте цифру";
  }
  if (!/[^A-Za-zА-Яа-яЁё0-9]/.test(password)) {
    return "Добавьте спецсимвол";
  }
  return undefined;
}

export function validateAuthForm({
  mode,
  email,
  username,
  password,
}: {
  mode: "login" | "register";
  email: string;
  username: string;
  password: string;
}): AuthValidationErrors {
  return {
    email: mode === "register" ? validateEmail(email) : undefined,
    username: validateUsername(username),
    password:
      mode === "register"
        ? validatePassword(password)
        : password
          ? undefined
          : "Укажите пароль",
  };
}

export function hasValidationErrors(errors: AuthValidationErrors): boolean {
  return Boolean(errors.email || errors.username || errors.password);
}
