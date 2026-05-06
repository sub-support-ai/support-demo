import {
  Alert,
  Badge,
  Group,
  LoadingOverlay,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import { getApiError } from "../api/client";
import { useStats } from "../api/stats";
import { getStatusLabel } from "../lib/ticketLabels";

function MetricCard({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: number | string;
  tone?: "neutral" | "warning" | "success";
}) {
  return (
    <Paper className={`metric-card ${tone}`} withBorder>
      <Text size="sm" c="dimmed">
        {label}
      </Text>
      <Text className="metric-value">{value}</Text>
    </Paper>
  );
}

export function DashboardPage() {
  const stats = useStats();
  const ticketStats = stats.data?.tickets;
  const aiStats = stats.data?.ai;
  const activeRequests =
    (ticketStats?.by_status.confirmed ?? 0) +
    (ticketStats?.by_status.in_progress ?? 0) +
    (ticketStats?.by_status.ai_processing ?? 0);

  return (
    <div className="content-page">
      <Paper className="dashboard-panel" withBorder>
        <LoadingOverlay visible={stats.isLoading} />
        <Group justify="space-between" mb="md">
          <div>
            <Title order={2}>Обзор</Title>
            <Text size="sm" c="dimmed">
              Состояние обращений, SLA и качества ответов.
            </Text>
          </div>
          <Badge variant="light">Live</Badge>
        </Group>

        {stats.error && (
          <Alert color="red" variant="light" mb="md">
            {getApiError(stats.error)}
          </Alert>
        )}

        <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }} spacing="md">
          <MetricCard label="Всего запросов" value={ticketStats?.total ?? 0} />
          <MetricCard label="Активно" value={activeRequests} />
          <MetricCard
            label="SLA просрочен"
            value={ticketStats?.sla_overdue_count ?? 0}
            tone={(ticketStats?.sla_overdue_count ?? 0) > 0 ? "warning" : "success"}
          />
          <MetricCard
            label="SLA эскалаций"
            value={ticketStats?.sla_escalated_count ?? 0}
            tone={(ticketStats?.sla_escalated_count ?? 0) > 0 ? "warning" : "neutral"}
          />
          <MetricCard
            label="Повторно открыто"
            value={ticketStats?.reopen_count ?? 0}
          />
          <MetricCard
            label="Решено без специалиста"
            value={aiStats?.resolved_by_ai_count ?? 0}
            tone="success"
          />
          <MetricCard
            label="Передано специалисту"
            value={aiStats?.escalated_count ?? 0}
          />
          <MetricCard
            label="Помогло"
            value={aiStats?.user_feedback_helped ?? 0}
            tone="success"
          />
          <MetricCard
            label="Не помогло"
            value={aiStats?.user_feedback_not_helped ?? 0}
            tone={(aiStats?.user_feedback_not_helped ?? 0) > 0 ? "warning" : "neutral"}
          />
        </SimpleGrid>

        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md" mt="md">
          <Paper className="dashboard-section" withBorder>
            <Title order={4} mb="sm">
              Статусы
            </Title>
            <Stack gap="xs">
              {Object.entries(ticketStats?.by_status ?? {}).map(([status, count]) => (
                <Group key={status} justify="space-between">
                  <Text size="sm">{getStatusLabel(status)}</Text>
                  <Badge variant="light">{count}</Badge>
                </Group>
              ))}
            </Stack>
          </Paper>
          <Paper className="dashboard-section" withBorder>
            <Title order={4} mb="sm">
              Отделы
            </Title>
            <Stack gap="xs">
              {Object.entries(ticketStats?.by_department ?? {}).map(([department, count]) => (
                <Group key={department} justify="space-between">
                  <Text size="sm">{department}</Text>
                  <Badge variant="light">{count}</Badge>
                </Group>
              ))}
            </Stack>
          </Paper>
        </SimpleGrid>
      </Paper>
    </div>
  );
}
