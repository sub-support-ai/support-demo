/**
 * Детекция потенциальных дубликатов тикетов.
 *
 * Гипотеза: если пользователь подтверждает черновик, а у него уже есть
 * открытый тикет с тем же `affected_item` (или той же связкой
 * `department + request_type`) — это с большой вероятностью одна и та же
 * проблема, и стоит предупредить, чтобы не плодить сущности.
 *
 * Намеренно НЕ используем семантическое сравнение через embeddings — для
 * первой версии простой keyword-матч даёт хорошую точность при нулевой
 * стоимости (всё клиентское, бэкенд не трогаем). При желании можно
 * добавить второй проход через AI-эндпоинт.
 *
 * Все сравнения case-insensitive с trim — пользователи вводят
 * «VPN», «vpn », «Vpn» как одно и то же.
 */

import type { Ticket } from "../api/types";

/**
 * Статусы, при которых тикет считается «активным» для целей дедупа.
 * Включаем pending_user (другой черновик) — пользователь должен знать,
 * что он уже начал похожий запрос.
 */
const OPEN_STATUSES = new Set([
  "pending_user",
  "confirmed",
  "in_progress",
  "ai_processing",
]);

function normalize(s: string | null | undefined): string {
  return (s ?? "").trim().toLowerCase();
}

/**
 * Возвращает список открытых тикетов того же пользователя, которые
 * похожи на текущий черновик по ключевым полям.
 *
 * Условия совпадения (любое):
 *   - тот же `affected_item` (например, оба про «VPN»)
 *   - тот же `department` + `request_type` (та же категория запроса
 *     в тот же отдел)
 *
 * Если у черновика нет ни одного из этих ключей — вернётся пустой массив:
 * не на чем строить вывод, а ложные срабатывания хуже, чем пропуски.
 */
export function findPotentialDuplicates(
  draft: Ticket,
  allTickets: ReadonlyArray<Ticket>,
): Ticket[] {
  const draftAffected = normalize(draft.affected_item);
  const draftType = normalize(draft.request_type);
  const draftDept = normalize(draft.department);

  const hasAffected = draftAffected.length > 0;
  const hasTypeAndDept = draftType.length > 0 && draftDept.length > 0;
  if (!hasAffected && !hasTypeAndDept) {
    return [];
  }

  return allTickets.filter((other) => {
    if (other.id === draft.id) return false;
    if (other.user_id !== draft.user_id) return false;
    if (!OPEN_STATUSES.has(other.status)) return false;

    const otherAffected = normalize(other.affected_item);
    const otherType = normalize(other.request_type);
    const otherDept = normalize(other.department);

    if (hasAffected && otherAffected && otherAffected === draftAffected) {
      return true;
    }
    if (
      hasTypeAndDept &&
      otherType === draftType &&
      otherDept === draftDept
    ) {
      return true;
    }
    return false;
  });
}
