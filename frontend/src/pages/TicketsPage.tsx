import {
  Alert,
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
  { value: "IT", label: "IT" },
  { value: "HR", label: "HR" },
  { value: "finance", label: "Финансы" },
];

const SLA_OPTIONS = [
  { value: "overdue", label: "SLA просрочен" },
  { value: "active", label: "SLA активен" },
];

export function TicketsPage() {
  const { token } = useAuth();
  const me = useMe(Boolean(token));
  const tickets = useTickets();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [department, setDepartment] = useState<string | null>(null);
  const [sla, setSla] = useState<string | null>(null);

  const isOperator = me.data?.role === "agent" || me.data?.role === "admin";
  const pageTitle = isOperator ? "Запросы" : "Мои запросы";
  const pageDescription =
    me.data?.role === "admin"
      ? "Все обращения пользователей, SLA и работа специалистов."
      : me.data?.role === "agent"
        ? "Назначенные вам обращения и рабочая очередь."
        : "Активные и отправленные обращения.";

  const filteredTickets = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (tickets.data ?? []).filter((ticket) => {
      const haystack = [
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
        .join("\n")
        .toLowerCase();

      if (query && !haystack.includes(query)) {
        return false;
      }
      if (status && ticket.status !== status) {
        return false;
      }
      if (department && ticket.department !== department) {
        return false;
      }
      if (sla === "overdue" && !ticket.is_sla_breached) {
        return false;
      }
      if (sla === "active" && (!ticket.sla_deadline_at || ticket.is_sla_breached)) {
        return false;
      }
      return true;
    });
  }, [department, search, sla, status, tickets.data]);

  const error = tickets.error || me.error;

  return (
    <div className="content-page">
      <Paper className="tickets-panel" withBorder>
        <LoadingOverlay visible={tickets.isLoading || me.isLoading} />
        <Title order={2} mb="xs">
          {pageTitle}
        </Title>
        <Text size="sm" c="dimmed" mb="md">
          {pageDescription}
        </Text>
        {error && (
          <Alert color="red" variant="light" mb="md">
            {getApiError(error)}
          </Alert>
        )}

        <div className="ticket-filters">
          <TextInput
            placeholder="Поиск по теме, офису, объекту или заявителю"
            value={search}
            onChange={(event) => setSearch(event.currentTarget.value)}
          />
          <Select
            placeholder="Статус"
            data={STATUS_OPTIONS}
            value={status}
            clearable
            onChange={setStatus}
          />
          <Select
            placeholder="Отдел"
            data={DEPARTMENT_OPTIONS}
            value={department}
            clearable
            onChange={setDepartment}
          />
          <Select
            placeholder="SLA"
            data={SLA_OPTIONS}
            value={sla}
            clearable
            onChange={setSla}
          />
        </div>

        {!filteredTickets.length && !tickets.isLoading ? (
          <div className="empty-state tickets">
            <Text fw={600}>
              {tickets.data?.length ? "По фильтрам запросов нет" : "Запросов нет"}
            </Text>
          </div>
        ) : (
          <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
            {filteredTickets.map((ticket) => (
              <TicketCard key={ticket.id} ticket={ticket} role={me.data?.role} />
            ))}
          </SimpleGrid>
        )}
      </Paper>
    </div>
  );
}
