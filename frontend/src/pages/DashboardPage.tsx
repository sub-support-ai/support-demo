import {
  Alert,
  Badge,
  Group,
  LoadingOverlay,
  Paper,
  Progress,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import { getApiError } from "../api/client";
import { useStats } from "../api/stats";
import { getStatusLabel } from "../lib/ticketLabels";

function percent(value: number): string {
  return `${Math.round(value)}%`;
}

function MetricCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <Paper className="metric-card" withBorder>
      <Text className="metric-label" size="xs" tt="uppercase" fw={700} c="dimmed">
        {label}
      </Text>
      <Text className="metric-value">{value}</Text>
      {hint && (
        <Text size="sm" c="dimmed">
          {hint}
        </Text>
      )}
    </Paper>
  );
}

function BreakdownList({
  items,
  labeler,
}: {
  items: Record<string, number>;
  labeler?: (key: string) => string;
}) {
  const entries = Object.entries(items);
  if (entries.length === 0) {
    return (
      <Text c="dimmed" size="sm">
        Данных пока нет
      </Text>
    );
  }

  const max = Math.max(...entries.map(([, value]) => value), 1);

  return (
    <Stack gap="sm">
      {entries.map(([key, value]) => (
        <div className="breakdown-row" key={key}>
          <Group justify="space-between" gap="sm" mb={6} wrap="nowrap">
            <Text size="sm" lineClamp={1}>
              {labeler?.(key) ?? key}
            </Text>
            <Badge variant="light">{value}</Badge>
          </Group>
          <Progress value={(value / max) * 100} size="sm" />
        </div>
      ))}
    </Stack>
  );
}

export function DashboardPage() {
  const stats = useStats();
  const data = stats.data;

  return (
    <div className="content-page dashboard-page">
      <Paper className="tickets-panel dashboard-panel" withBorder>
        <LoadingOverlay visible={stats.isLoading} />
        <div className="dashboard-header">
          <div>
            <Title order={2}>Обзор</Title>
            <Text size="sm" c="dimmed">
              Живая статистика по запросам, маршрутизации и качеству ответов.
            </Text>
          </div>
        </div>

        {stats.error && (
          <Alert color="red" variant="light" mb="md">
            {getApiError(stats.error)}
          </Alert>
        )}

        {data && (
          <Stack gap="lg">
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }} spacing="md">
              <MetricCard label="Всего запросов" value={data.tickets.total} />
              <MetricCard
                label="Обработано"
                value={data.ai.total_processed}
                hint="записей в журнале обработки"
              />
              <MetricCard
                label="Низкая уверенность"
                value={data.ai.low_confidence_count}
                hint="требуют проверки"
              />
              <MetricCard
                label="SLA просрочен"
                value={data.tickets.sla_overdue_count}
                hint="открытые запросы"
              />
              <MetricCard
                label="Роутинг"
                value={percent(data.ai.routing_accuracy_pct)}
                hint="подтверждено агентами"
              />
            </SimpleGrid>

            <SimpleGrid cols={{ base: 1, md: 3 }} spacing="md">
              <Paper className="quiet-panel dashboard-section" withBorder>
                <Title order={4} mb="sm">
                  По статусам
                </Title>
                <BreakdownList
                  items={data.tickets.by_status}
                  labeler={getStatusLabel}
                />
              </Paper>
              <Paper className="quiet-panel dashboard-section" withBorder>
                <Title order={4} mb="sm">
                  По отделам
                </Title>
                <BreakdownList items={data.tickets.by_department} />
              </Paper>
              <Paper className="quiet-panel dashboard-section" withBorder>
                <Title order={4} mb="sm">
                  По источникам
                </Title>
                <BreakdownList items={data.tickets.by_source} />
              </Paper>
            </SimpleGrid>

            <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }} spacing="md">
              <MetricCard label="Эскалации" value={data.ai.escalated_count} />
              <MetricCard
                label="Решено без специалиста"
                value={data.ai.resolved_by_ai_count}
              />
              <MetricCard
                label="Помогло / не помогло"
                value={`${data.ai.user_feedback_helped} / ${data.ai.user_feedback_not_helped}`}
              />
            </SimpleGrid>
          </Stack>
        )}
      </Paper>
    </div>
  );
}
