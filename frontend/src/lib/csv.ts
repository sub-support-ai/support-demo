/**
 * Утилиты для экспорта тикетов в CSV.
 *
 * Формат:
 *   - UTF-8 + BOM (`﻿`) — без BOM Excel читает кириллицу кракозябрами
 *   - Разделитель `;` — русский Excel по умолчанию ожидает именно его
 *     (потому что `,` используется как десятичный разделитель)
 *   - Перевод строк CRLF — RFC 4180 и Excel-friendly
 *   - Ячейки с `;`, `"` или переводом строки оборачиваются в кавычки,
 *     внутренние кавычки экранируются удвоением (`"` → `""`)
 */

import type { Ticket } from "../api/types";
import {
  getDepartmentLabel,
  getStatusLabel,
  getTicketKindLabel,
  getTicketPriorityLabel,
} from "./ticketLabels";

/** Описание одной колонки: заголовок и функция извлечения значения. */
export interface CsvColumn<T> {
  label: string;
  value: (item: T) => string | number | null | undefined;
}

/** Колонки для CSV экспорта тикета. Порядок важен. */
export const TICKET_CSV_COLUMNS: ReadonlyArray<CsvColumn<Ticket>> = [
  { label: "ID", value: (t) => t.id },
  { label: "Создан", value: (t) => t.created_at },
  { label: "Обновлён", value: (t) => t.updated_at },
  { label: "Статус", value: (t) => getStatusLabel(t.status) },
  { label: "Отдел", value: (t) => getDepartmentLabel(t.department) },
  { label: "Тип", value: (t) => getTicketKindLabel(t.ticket_kind) },
  { label: "Приоритет", value: (t) => getTicketPriorityLabel(t) },
  { label: "Тема", value: (t) => t.title },
  { label: "Заявитель", value: (t) => t.requester_name },
  { label: "Email", value: (t) => t.requester_email },
  { label: "Офис", value: (t) => t.office },
  { label: "Объект", value: (t) => t.affected_item },
  { label: "Тип запроса", value: (t) => t.request_type },
  { label: "SLA дедлайн", value: (t) => t.sla_deadline_at },
  { label: "SLA нарушен", value: (t) => (t.is_sla_breached ? "да" : "нет") },
  { label: "AI категория", value: (t) => t.ai_category },
  { label: "Решён", value: (t) => t.resolved_at },
  { label: "Повторно открыт", value: (t) => t.reopen_count ?? 0 },
];

/** Экранирует одну ячейку: оборачивает в кавычки, если содержит `;`, `"` или \n. */
export function escapeCsvCell(value: string | number | null | undefined): string {
  if (value == null) return "";
  const str = String(value);
  if (/[;"\r\n]/.test(str)) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

/** Превращает массив объектов в CSV-строку по описанию колонок. */
export function toCsv<T>(items: ReadonlyArray<T>, columns: ReadonlyArray<CsvColumn<T>>): string {
  const header = columns.map((c) => escapeCsvCell(c.label)).join(";");
  const rows = items.map((item) =>
    columns.map((c) => escapeCsvCell(c.value(item))).join(";"),
  );
  return [header, ...rows].join("\r\n");
}

/** Шорткат для тикетов — фиксированные колонки. */
export function ticketsToCsv(tickets: ReadonlyArray<Ticket>): string {
  return toCsv(tickets, TICKET_CSV_COLUMNS);
}

/**
 * Триггерит скачивание CSV-файла в браузере.
 *
 * Если имя файла не передано — по умолчанию `tickets-YYYY-MM-DD.csv`.
 * Не тестируется напрямую (DOM-side effects), но логика разделена так,
 * что `ticketsToCsv` можно валидировать в изоляции.
 */
export function downloadTicketsCsv(
  tickets: ReadonlyArray<Ticket>,
  filename?: string,
): void {
  const csv = ticketsToCsv(tickets);
  // BOM — критичен для корректного отображения кириллицы в Excel.
  const bom = "﻿";
  const blob = new Blob([bom + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename ?? `tickets-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
