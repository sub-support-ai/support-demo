import {
  Alert,
  Group,
  LoadingOverlay,
  Paper,
  Select,
  SimpleGrid,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMemo, useState } from "react";

import { useMe } from "../api/auth";
import { getApiError } from "../api/client";
import { useTickets } from "../api/tickets";
import { TicketCard } from "../components/tickets/TicketCard";
import { getStatusLabel } from "../lib/ticketLabels";
import { useAuth } from "../stores/auth";

const STATUS_OPTIONS = [
  "pending_user",
  "confirmed",
  "in_progress",
  "closed",
  "resolved",
].map((status) => ({ value: status, label: getStatusLabel(status) }));

const DEPARTMENT_OPTIONS = [
  { value: "IT", label: "ИТ" },
  { value: "HR", label: "Кадры" },
  { value: "finance", label: "Финансы" },
  { value: "procurement", label: "Закупки" },
  { value: "security", label: "Безопасность" },
  { value: "facilities", label: "АХО" },
  { value: "documents", label: "Документооборот" },
];

const SLA_OPTIONS = [
  { value: "overdue", label: "SLA просрочен" },
  { value: "active", label: "SLA в норме" },
];

export function TicketsPage() {
  const { token } = useAuth();
  const me = useMe(Boolean(token));
  const tickets = useTickets();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [departmentFilter, setDepartmentFilter] = useState<string | null>(null);
  const [slaFilter, setSlaFilter] = useState<string | null>(null);

  const role = me.data?.role;
  const title = role === "admin" || role === "agent" ? "Запросы" : "Мои запросы";
  const description =
    role === "admin"
      ? "Все обращения пользователей. Подтвержденные запросы можно взять в работу или закрыть."
      : role === "agent"
        ? "Назначенные вам обращения. Подтвержденные запросы можно взять в работу или закрыть."
        : "Активные и отправленные обращения.";

  const visibleTickets = useMemo(() => {
    const query = search.trim().toLowerCase();
    return tickets.data?.filter((ticket) => {
      const matchesSearch =
        !query ||
        [
          ticket.title,
          ticket.body,
          ticket.requester_name,
          ticket.requester_email,
          ticket.office,
          ticket.affected_item,
          ticket.request_type,
          ticket.request_details,
        ]
          .filter(Boolean)
          .some((value) => value!.toLowerCase().includes(query));
      const matchesStatus = !statusFilter || ticket.status === statusFilter;
      const matchesDepartment =
        !departmentFilter || ticket.department === departmentFilter;
      const matchesSla =
        !slaFilter ||
        (slaFilter === "overdue" && ticket.is_sla_breached) ||
        (slaFilter === "active" && ticket.sla_deadline_at && !ticket.is_sla_breached);
      return matchesSearch && matchesStatus && matchesDepartment && matchesSla;
    });
  }, [departmentFilter, search, slaFilter, statusFilter, tickets.data]);

  const error = tickets.error || me.error;

  return (
    <div className="content-page">
      <Paper className="tickets-panel" withBorder>
        <LoadingOverlay visible={tickets.isLoading || me.isLoading} />
        <Title order={2} mb="xs">
          {title}
        </Title>
        <Text size="sm" c="dimmed" mb="md">
          {description}
        </Text>

        <Group className="ticket-filters" align="end" mb="md">
          <TextInput
            label="Поиск"
            placeholder="Тема, заявитель, офис, объект"
            value={search}
            onChange={(event) => setSearch(event.currentTarget.value)}
          />
          <Select
            label="Статус"
            data={STATUS_OPTIONS}
            value={statusFilter}
            clearable
            onChange={setStatusFilter}
          />
          <Select
            label="Отдел"
            data={DEPARTMENT_OPTIONS}
            value={departmentFilter}
            clearable
            onChange={setDepartmentFilter}
          />
          <Select
            label="SLA"
            data={SLA_OPTIONS}
            value={slaFilter}
            clearable
            onChange={setSlaFilter}
          />
        </Group>

        {error && (
          <Alert color="red" variant="light" mb="md">
            {getApiError(error)}
          </Alert>
        )}

        {!visibleTickets?.length && !tickets.isLoading ? (
          <div className="empty-state tickets">
            <Text fw={600}>
              {tickets.data?.length ? "По фильтрам запросов нет" : "Запросов нет"}
            </Text>
          </div>
        ) : (
          <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
            {visibleTickets?.map((ticket) => (
              <TicketCard
                key={ticket.id}
                ticket={ticket}
                currentUserRole={me.data?.role}
              />
            ))}
          </SimpleGrid>
        )}
      </Paper>
    </div>
  );
}
