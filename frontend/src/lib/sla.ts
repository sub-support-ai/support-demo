/**
 * Утилиты для отображения SLA-дедлайнов в разных контекстах.
 *
 * Сотрудник (пользователь) и оператор смотрят на одну и ту же дату по-разному:
 *
 *   Сотрудник: «когда мне ответят?» → нужна абсолютная время-точка
 *     («до 15:00 сегодня», «до 10:00 завтра», «до 12:00 в пятницу»)
 *
 *   Оператор: «сколько у меня времени?» → нужна относительная дельта
 *     («3 ч до дедлайна», «просрочен 1 ч 20 мин»)
 *
 * Поэтому здесь два форматтера. Общий — `getDeadlineStatus`, который
 * классифицирует дедлайн в одну из 4 категорий для единообразной
 * цветовой кодировки.
 */

export type DeadlineStatus = "breached" | "urgent" | "warning" | "ok";

/**
 * Возвращает категорию дедлайна по оставшемуся времени.
 *  - `breached` — просрочен или `is_sla_breached=true`
 *  - `urgent`   — < 2 часов
 *  - `warning`  — < 8 часов
 *  - `ok`       — больше 8 часов
 *  - `null`     — дедлайна нет / невалидное значение
 *
 * Принимает опциональный `now` для тестирования.
 */
export function getDeadlineStatus(
  value: string | null | undefined,
  options: { breached?: boolean | null; now?: Date } = {},
): DeadlineStatus | null {
  if (!value) return null;
  const ts = new Date(value).getTime();
  if (Number.isNaN(ts)) return null;
  const nowMs = (options.now ?? new Date()).getTime();
  const diffMs = ts - nowMs;
  if (options.breached || diffMs < 0) return "breached";
  const diffH = diffMs / 3_600_000;
  if (diffH < 2) return "urgent";
  if (diffH < 8) return "warning";
  return "ok";
}

/** Mantine-цвет для бейджа по статусу. */
export function getDeadlineColor(status: DeadlineStatus): string {
  switch (status) {
    case "breached":
      return "red";
    case "urgent":
      return "orange";
    case "warning":
      return "yellow";
    case "ok":
      return "teal";
  }
}

const WEEKDAY_NOMINATIVE: Record<number, string> = {
  0: "воскресенье",
  1: "понедельник",
  2: "вторник",
  3: "среда",
  4: "четверг",
  5: "пятница",
  6: "суббота",
};

function startOfDay(d: Date): Date {
  const out = new Date(d);
  out.setHours(0, 0, 0, 0);
  return out;
}

function addDays(d: Date, days: number): Date {
  const out = new Date(d);
  out.setDate(out.getDate() + days);
  return out;
}

/**
 * Дружелюбный текст дедлайна для сотрудника.
 *
 *   до 15:00 сегодня
 *   до 10:00 завтра
 *   до 12:00 в пятницу     (через 2-6 дней — день недели читается легче даты)
 *   до 12:00, 03.06          (через 7+ дней — день недели уже не информативен)
 *   истёк срок ответа        (просрочен)
 *
 * Принимает опциональный `now` для тестирования.
 */
export function formatFriendlyDeadline(
  value: string | null | undefined,
  options: { breached?: boolean | null; now?: Date } = {},
): string | null {
  if (!value) return null;
  const deadline = new Date(value);
  if (Number.isNaN(deadline.getTime())) return null;

  const now = options.now ?? new Date();
  if (options.breached || deadline.getTime() < now.getTime()) {
    return "истёк срок ответа";
  }

  const timeStr = deadline.toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  });

  const today = startOfDay(now);
  const tomorrow = addDays(today, 1);
  const dayAfter = addDays(today, 2);
  const inAWeek = addDays(today, 7);

  if (deadline < tomorrow) return `до ${timeStr} сегодня`;
  if (deadline < dayAfter) return `до ${timeStr} завтра`;
  if (deadline < inAWeek) {
    const weekday = WEEKDAY_NOMINATIVE[deadline.getDay()];
    // «в среду / в пятницу» — звучит естественно по-русски,
    // в отличие от «среда» как обрезка из локали.
    const weekdayPhrase = weekday === "среда" || weekday === "пятница" || weekday === "суббота"
      ? `в ${weekday.slice(0, -1)}у` // в среду, в пятницу, в субботу
      : weekday === "воскресенье"
        ? "в воскресенье"
        : `в ${weekday}`; // в понедельник, во вторник (без склонения)
    return `до ${timeStr} ${weekdayPhrase}`;
  }

  const date = deadline.toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
  });
  return `до ${timeStr}, ${date}`;
}

/**
 * Краткий текст дедлайна для оператора — относительная дельта.
 *
 *   просрочен 2 ч 15 мин
 *   30 мин до дедлайна
 *   5 ч до дедлайна
 *   null                    (если дедлайна нет или ещё > 8 ч)
 */
export function formatOperatorDeadline(
  value: string | null | undefined,
  options: { breached?: boolean | null; now?: Date } = {},
): string | null {
  if (!value) return null;
  const ts = new Date(value).getTime();
  if (Number.isNaN(ts)) return null;

  const nowMs = (options.now ?? new Date()).getTime();
  const diffMs = ts - nowMs;

  if (options.breached || diffMs < 0) {
    const absMs = Math.abs(diffMs);
    const h = Math.floor(absMs / 3_600_000);
    const m = Math.floor((absMs % 3_600_000) / 60_000);
    return h > 0 ? `просрочен ${h} ч ${m} мин` : `просрочен ${m} мин`;
  }

  const diffH = diffMs / 3_600_000;
  if (diffH < 2) {
    const remainM = Math.floor(diffMs / 60_000);
    return `${remainM} мин до дедлайна`;
  }
  if (diffH < 8) {
    return `${Math.floor(diffH)} ч до дедлайна`;
  }
  return null;
}
