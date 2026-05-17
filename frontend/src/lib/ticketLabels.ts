import type { Ticket } from "../api/types";

const DEPARTMENT_LABELS: Record<string, string> = {
  IT: "ИТ",
  HR: "Кадры",
  finance: "Финансы",
  procurement: "Закупки",
  security: "Безопасность",
  facilities: "Офис и помещения",
  documents: "Документооборот",
};

const STATUS_LABELS: Record<string, string> = {
  new: "Новый",
  pending_user: "Ожидает подтверждения",
  confirmed: "Отправлен в отдел",
  in_progress: "В работе",
  resolved: "Решен",
  closed: "Закрыт",
  ai_processing: "Обрабатывается",
  declined: "Отклонен",
  escalated: "Передан специалисту",
  active: "Активен",
};

const USER_PRIORITY_LABELS: Record<number, string> = {
  2: "Высокий",
  3: "Средний",
  4: "Низкий",
  5: "Плановый",
};

const AI_PRIORITY_LABELS: Record<string, string> = {
  низкий: "Низкий",
  средний: "Средний",
  высокий: "Высокий",
  критический: "Критический",
};

export function getStatusLabel(status?: string | null): string {
  if (!status) {
    return "Статус неизвестен";
  }
  return STATUS_LABELS[status] ?? status;
}

export function getUserPriorityLabel(priority?: number | null): string {
  if (!priority) {
    return "Приоритет не указан";
  }
  return USER_PRIORITY_LABELS[priority] ?? `Приоритет ${priority}`;
}

export function getAiPriorityLabel(priority?: string | null): string | null {
  if (!priority) {
    return null;
  }
  return AI_PRIORITY_LABELS[priority.toLowerCase()] ?? priority;
}

export function getTicketPriorityLabel(ticket: Ticket): string {
  return getAiPriorityLabel(ticket.ai_priority) ?? getUserPriorityLabel(ticket.user_priority);
}

export function getDepartmentLabel(department?: string | null): string {
  if (!department) return "Без отдела";
  return DEPARTMENT_LABELS[department] ?? department;
}

const TICKET_KIND_LABELS: Record<string, string> = {
  incident: "Инцидент",
  service_request: "Запрос услуги",
  access_request: "Запрос доступа",
  security_incident: "Инцидент ИБ",
};

const TICKET_KIND_COLORS: Record<string, string> = {
  incident: "red",
  service_request: "blue",
  access_request: "violet",
  security_incident: "orange",
};

export function getTicketKindLabel(kind?: string | null): string {
  if (!kind) return "Инцидент";
  return TICKET_KIND_LABELS[kind] ?? kind;
}

export function getTicketKindColor(kind?: string | null): string {
  if (!kind) return "red";
  return TICKET_KIND_COLORS[kind] ?? "gray";
}
