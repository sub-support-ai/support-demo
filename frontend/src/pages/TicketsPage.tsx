import {
  Alert,
  Badge,
  Button,
  Group,
  LoadingOverlay,
  Paper,
  Select,
  SimpleGrid,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { IconDownload } from "@tabler/icons-react";
import { useMemo, useState } from "react";

import { useMe } from "../api/auth";
import { getApiError } from "../api/client";
import { useTickets } from "../api/tickets";
import { TicketCard } from "../components/tickets/TicketCard";
import { downloadTicketsCsv } from "../lib/csv";
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

type TicketQueue =
  | "active"
  | "new"
  | "in_progress"
  | "overdue"
  | "unassigned"
  | "pending_user"
  | "resolved"
  | "all";

const OPERATOR_QUEUES: Array<{
  value: TicketQueue;
  label: string;
  description: string;
}> = [
  {
    value: "active",
    label: "Активные",
    description: "Все подтверждённые запросы, которые ещё не закрыты.",
  },
  {
    value: "new",
    label: "Новые",
    description: "Запросы отправлены в отдел, агент ещё не начал работу.",
  },
  {
    value: "in_progress",
    label: "В работе",
    description: "Запросы уже взяты в обработку.",
  },
  {
    value: "overdue",
    label: "Просрочены",
    description: "Запросы с нарушенным SLA требуют первоочередной реакции.",
  },
  {
    value: "unassigned",
    label: "Без исполнителя",
    description: "Подтверждённые запросы, которым не назначен агент.",
  },
  {
    value: "pending_user",
    label: "Ждут пользователя",
    description: "Черновики, которые пользователь ещё не отправил в отдел.",
  },
  {
    value: "resolved",
    label: "Завершены",
    description: "Решённые и закрытые запросы.",
  },
  {
    value: "all",
    label: "Все",
    description: "Полный список запросов с учётом фильтров.",
  },
];

const USER_QUEUES: Array<{
  value: TicketQueue;
  label: string;
  description: string;
}> = [
  {
    value: "active",
    label: "Активные",
    description: "Ваши отправленные запросы, которые ещё обрабатываются.",
  },
  {
    value: "pending_user",
    label: "Черновики",
    description: "Черновики ожидают проверки и отправки.",
  },
  {
    value: "resolved",
    label: "Завершены",
    description: "Решённые и закрытые обращения.",
  },
  {
    value: "all",
    label: "Все",
    description: "Все ваши обращения с учётом фильтров.",
  },
];

function isActiveTicket(ticket: { status: string; confirmed_by_user: boolean }) {
  return ticket.confirmed_by_user && ["confirmed", "in_progress"].includes(ticket.status);
}

function isResolvedTicket(ticket: { status: string }) {
  return ["resolved", "closed", "declined"].includes(ticket.status);
}

function matchesQueue(
  ticket: {
    status: string;
    confirmed_by_user: boolean;
    is_sla_breached?: boolean;
    agent_id?: number | null;
  },
  queue: TicketQueue,
) {
  if (queue === "all") return true;
  if (queue === "active") return isActiveTicket(ticket);
  if (queue === "new") return ticket.status === "confirmed";
  if (queue === "in_progress") return ticket.status === "in_progress";
  if (queue === "overdue") return isActiveTicket(ticket) && Boolean(ticket.is_sla_breached);
  if (queue === "unassigned") {
    return isActiveTicket(ticket) && ticket.agent_id == null;
  }
  if (queue === "pending_user") {
    return ticket.status === "pending_user" && !ticket.confirmed_by_user;
  }
  if (queue === "resolved") return isResolvedTicket(ticket);
  return true;
}

function getPriorityRank(priority?: string | null, userPriority?: number | null) {
  const normalized = priority?.toLowerCase();
  if (normalized === "критический") return 0;
  if (normalized === "высокий") return 1;
  if (normalized === "средний") return 2;
  if (normalized === "низкий") return 3;
  if (typeof userPriority === "number") {
    return Math.max(0, Math.min(4, userPriority - 1));
  }
  return 4;
}

function getTicketSortScore(ticket: {
  status: string;
  is_sla_breached?: boolean;
  agent_id?: number | null;
  ai_priority?: string | null;
  user_priority?: number | null;
  created_at: string;
}) {
  const slaScore = ticket.is_sla_breached ? 0 : 1;
  const unassignedScore =
    ticket.agent_id == null && ["confirmed", "in_progress"].includes(ticket.status)
      ? 0
      : 1;
  const statusScore = ticket.status === "confirmed" ? 0 : ticket.status === "in_progress" ? 1 : 2;
  const priorityScore = getPriorityRank(ticket.ai_priority, ticket.user_priority);
  const createdTime = new Date(ticket.created_at).getTime();
  return [
    slaScore,
    unassignedScore,
    statusScore,
    priorityScore,
    Number.isNaN(createdTime) ? 0 : -createdTime,
  ];
}

function compareTicketsByQueue(left: Parameters<typeof getTicketSortScore>[0], right: Parameters<typeof getTicketSortScore>[0]) {
  const leftScore = getTicketSortScore(left);
  const rightScore = getTicketSortScore(right);
  for (let index = 0; index < leftScore.length; index += 1) {
    if (leftScore[index] !== rightScore[index]) {
      return leftScore[index] - rightScore[index];
    }
  }
  return 0;
}

export function TicketsPage() {
  const { token } = useAuth();
  const me = useMe(Boolean(token));
  const tickets = useTickets();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [departmentFilter, setDepartmentFilter] = useState<string | null>(null);
  const [slaFilter, setSlaFilter] = useState<string | null>(null);
  const [queue, setQueue] = useState<TicketQueue>("active");

  const role = me.data?.role;
  const isOperator = role === "admin" || role === "agent";
  const queueOptions = isOperator ? OPERATOR_QUEUES : USER_QUEUES;
  const activeQueue =
    queueOptions.some((item) => item.value === queue) ? queue : "active";
  const activeQueueDescription =
    queueOptions.find((item) => item.value === activeQueue)?.description ?? "";
  const title = role === "admin" || role === "agent" ? "Запросы" : "Мои запросы";
  const description =
    role === "admin"
      ? "Все обращения пользователей. Подтвержденные запросы можно взять в работу или закрыть."
      : role === "agent"
        ? "Назначенные вам обращения. Подтвержденные запросы можно взять в работу или закрыть."
        : "Активные и отправленные обращения.";

  const ticketCounts = useMemo(() => {
    const source = tickets.data ?? [];
    return queueOptions.reduce<Record<TicketQueue, number>>((acc, item) => {
      acc[item.value] = source.filter((ticket) => matchesQueue(ticket, item.value)).length;
      return acc;
    }, {} as Record<TicketQueue, number>);
  }, [queueOptions, tickets.data]);

  const visibleTickets = useMemo(() => {
    const query = search.trim().toLowerCase();
    return tickets.data?.filter((ticket) => {
      const matchesCurrentQueue = matchesQueue(ticket, activeQueue);
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
      return (
        matchesCurrentQueue &&
        matchesSearch &&
        matchesStatus &&
        matchesDepartment &&
        matchesSla
      );
    }).sort(compareTicketsByQueue);
  }, [activeQueue, departmentFilter, search, slaFilter, statusFilter, tickets.data]);

  const activeCount = tickets.data?.filter(isActiveTicket).length ?? 0;
  const overdueCount =
    tickets.data?.filter((ticket) => isActiveTicket(ticket) && ticket.is_sla_breached)
      .length ?? 0;
  const unassignedCount =
    tickets.data?.filter(
      (ticket) => isActiveTicket(ticket) && ticket.agent_id == null,
    ).length ?? 0;

  const error = tickets.error || me.error;

  return (
    <div className="content-page">
      <Paper className="tickets-panel" withBorder>
        <LoadingOverlay visible={tickets.isLoading || me.isLoading} />
        <Group justify="space-between" align="flex-start" mb="md" wrap="nowrap" gap="md">
          <div style={{ minWidth: 0, flex: 1 }}>
            <Title order={2} mb="xs">
              {title}
            </Title>
            <Text size="sm" c="dimmed">
              {description}
            </Text>
          </div>
          <Button
            variant="light"
            size="sm"
            leftSection={<IconDownload size={16} />}
            disabled={!visibleTickets || visibleTickets.length === 0}
            onClick={() => {
              if (!visibleTickets?.length) return;
              const today = new Date().toISOString().slice(0, 10);
              // Имя файла включает текущую очередь — чтобы при экспорте
              // нескольких срезов файлы не перетирали друг друга в Downloads.
              downloadTicketsCsv(visibleTickets, `tickets-${activeQueue}-${today}.csv`);
            }}
          >
            Экспорт CSV
          </Button>
        </Group>

        {isOperator && (
          <SimpleGrid
            className="ticket-queue-summary"
            cols={{ base: 1, sm: 3 }}
            spacing="sm"
            mb="md"
          >
            <div className="queue-summary-item">
              <Text size="xs" c="dimmed" fw={600}>
                Активные
              </Text>
              <Text className="queue-summary-value">{activeCount}</Text>
            </div>
            <div className={`queue-summary-item${overdueCount ? " danger" : ""}`}>
              <Text size="xs" c="dimmed" fw={600}>
                Просрочены
              </Text>
              <Text className="queue-summary-value">{overdueCount}</Text>
            </div>
            <div className={`queue-summary-item${unassignedCount ? " warning" : ""}`}>
              <Text size="xs" c="dimmed" fw={600}>
                Без исполнителя
              </Text>
              <Text className="queue-summary-value">{unassignedCount}</Text>
            </div>
          </SimpleGrid>
        )}

        <Tabs
          value={activeQueue}
          onChange={(value) => value && setQueue(value as TicketQueue)}
          mb="md"
        >
          <Tabs.List>
            {queueOptions.map((item) => (
              <Tabs.Tab key={item.value} value={item.value}>
                <Group gap={6} wrap="nowrap">
                  <span>{item.label}</span>
                  <Badge size="xs" variant="light">
                    {ticketCounts[item.value] ?? 0}
                  </Badge>
                </Group>
              </Tabs.Tab>
            ))}
          </Tabs.List>
        </Tabs>

        <Text size="sm" c="dimmed" mb="md">
          {activeQueueDescription}
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
