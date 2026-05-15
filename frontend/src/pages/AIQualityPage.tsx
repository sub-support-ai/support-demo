import {
  Alert,
  Badge,
  Group,
  LoadingOverlay,
  Paper,
  Progress,
  RingProgress,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import { useMe } from "../api/auth";
import { useAIFallbacksStats, useStats } from "../api/stats";

// Стабильные reason-коды из AIFallbackEvent.reason
const FALLBACK_REASON_LABELS: Record<string, string> = {
  timeout: "Таймаут",
  connect: "Не достучались",
  http_5xx: "Ошибка сервера",
  broken_json: "Битый JSON",
  empty_response: "Пустой ответ",
};

function MetricCard({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "neutral" | "warning" | "success";
}) {
  return (
    <Paper className={`metric-card ${tone}`} withBorder>
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

  const max = Math.max(...entries.map(([, v]) => v), 1);

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

export function AIQualityPage() {
  const { data: me } = useMe(true);
  const isAdmin = me?.role === "admin";
  const stats = useStats();
  const fallbacks = useAIFallbacksStats(isAdmin);

  if (!isAdmin) {
    return (
      <Alert color="red" title="Доступ запрещён">
        Только для администраторов
      </Alert>
    );
  }

  const isLoading = stats.isLoading || fallbacks.isLoading;
  const ai = stats.data?.ai;
  const tickets = stats.data?.tickets;

  // Deflection rate: доля тикетов, закрытых AI, без эскалации
  const deflectionTotal = (ai?.resolved_by_ai_count ?? 0) + (ai?.escalated_count ?? 0);
  const deflectionRate =
    deflectionTotal > 0
      ? Math.round(((ai?.resolved_by_ai_count ?? 0) / deflectionTotal) * 100)
      : 0;

  const confidencePct = Math.round((ai?.avg_confidence ?? 0) * 100);
  const confidenceColor =
    confidencePct >= 80 ? "green" : confidencePct >= 60 ? "yellow" : "red";

  const routingPct = Math.round(ai?.routing_accuracy_pct ?? 0);
  const routingColor = routingPct >= 80 ? "green" : routingPct >= 60 ? "yellow" : "red";

  const csatScore = tickets?.avg_csat_score;

  return (
    <Stack gap="lg" p="md">
      <Title order={2}>Качество AI</Title>

      <div style={{ position: "relative", minHeight: 60 }}>
        <LoadingOverlay visible={isLoading} />

        <Stack gap="xl">
          {/* --- Основные метрики --- */}
          <SimpleGrid cols={{ base: 2, sm: 3, lg: 4 }} spacing="md">
            <MetricCard
              label="Обработано AI"
              value={ai?.total_processed ?? 0}
              hint="Всего диалогов"
            />
            <MetricCard
              label="Низкая уверенность"
              value={ai?.low_confidence_count ?? 0}
              hint="Требуют проверки агента"
              tone={
                (ai?.low_confidence_count ?? 0) > 10 ? "warning" : "neutral"
              }
            />
            <MetricCard
              label="Передано специалисту"
              value={ai?.escalated_count ?? 0}
              hint="Эскалировано из AI"
            />
            <MetricCard
              label="Закрыто AI"
              value={ai?.resolved_by_ai_count ?? 0}
              hint="Без участия агента"
              tone={
                (ai?.resolved_by_ai_count ?? 0) > 0 ? "success" : "neutral"
              }
            />
          </SimpleGrid>

          {/* --- Уверенность и точность роутинга --- */}
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
            <Paper withBorder p="md">
              <Group align="flex-start" gap="lg">
                <RingProgress
                  size={100}
                  thickness={10}
                  sections={[{ value: confidencePct, color: confidenceColor }]}
                  label={
                    <Text size="sm" fw={700} ta="center">
                      {confidencePct}%
                    </Text>
                  }
                />
                <Stack gap="xs">
                  <Text size="xs" tt="uppercase" fw={700} c="dimmed">
                    Средняя уверенность AI
                  </Text>
                  <Text size="xl" fw={700} c={confidenceColor}>
                    {confidencePct}%
                  </Text>
                  <Text size="sm" c="dimmed">
                    {confidencePct >= 80
                      ? "Хороший уровень"
                      : confidencePct >= 60
                        ? "Приемлемый уровень"
                        : "Требует внимания"}
                  </Text>
                </Stack>
              </Group>
            </Paper>

            <Paper withBorder p="md">
              <Stack gap="sm">
                <Text size="xs" tt="uppercase" fw={700} c="dimmed">
                  Точность роутинга
                </Text>
                <Group align="baseline" gap="xs">
                  <Text size="xl" fw={700} c={routingColor}>
                    {routingPct}%
                  </Text>
                  <Text size="sm" c="dimmed">
                    верных назначений
                  </Text>
                </Group>
                <Progress value={routingPct} color={routingColor} size="lg" radius="sm" />
                <Group gap="md">
                  <Text size="xs" c="dimmed">
                    Верно: {ai?.routing_correct_count ?? 0}
                  </Text>
                  <Text size="xs" c="dimmed">
                    Ошибок: {ai?.routing_incorrect_count ?? 0}
                  </Text>
                </Group>
              </Stack>
            </Paper>
          </SimpleGrid>

          {/* --- Deflection + CSAT + Feedback --- */}
          <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="md">
            <Paper withBorder p="md">
              <Stack gap="xs">
                <Text size="xs" tt="uppercase" fw={700} c="dimmed">
                  Отклонение (Deflection)
                </Text>
                <Text size="xl" fw={700}>
                  {deflectionRate}%
                </Text>
                <Text size="sm" c="dimmed">
                  Решено AI из всех обработанных (AI + эскалации)
                </Text>
              </Stack>
            </Paper>

            <Paper withBorder p="md">
              <Stack gap="xs">
                <Text size="xs" tt="uppercase" fw={700} c="dimmed">
                  CSAT (оценка качества)
                </Text>
                <Text size="xl" fw={700}>
                  {csatScore != null ? `${csatScore.toFixed(1)} / 5.0` : "—"}
                </Text>
                <Text size="sm" c="dimmed">
                  Средняя оценка удовлетворённости (1–5)
                </Text>
              </Stack>
            </Paper>

            <Paper withBorder p="md">
              <Stack gap="xs">
                <Text size="xs" tt="uppercase" fw={700} c="dimmed">
                  Обратная связь
                </Text>
                <Group gap="md">
                  <Stack gap={2} align="center">
                    <Text size="lg" fw={700} c="teal">
                      {ai?.user_feedback_helped ?? 0}
                    </Text>
                    <Text size="xs" c="dimmed">
                      Помогло
                    </Text>
                  </Stack>
                  <Stack gap={2} align="center">
                    <Text size="lg" fw={700} c="orange">
                      {ai?.user_feedback_not_helped ?? 0}
                    </Text>
                    <Text size="xs" c="dimmed">
                      Не помогло
                    </Text>
                  </Stack>
                </Group>
              </Stack>
            </Paper>
          </SimpleGrid>

          {/* --- Сбои AI за 24ч --- */}
          <Paper withBorder p="md">
            <Stack gap="md">
              <Group justify="space-between" align="center">
                <Text size="xs" tt="uppercase" fw={700} c="dimmed">
                  Сбои AI за 24 ч
                </Text>
                {fallbacks.data && (
                  <Badge
                    color={fallbacks.data.total > 0 ? "red" : "green"}
                    variant="filled"
                    size="lg"
                  >
                    {fallbacks.data.total}
                  </Badge>
                )}
              </Group>

              {fallbacks.isLoading ? (
                <Text size="sm" c="dimmed">
                  Загрузка...
                </Text>
              ) : fallbacks.data ? (
                <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
                  <Stack gap="xs">
                    <Text size="sm" fw={600}>
                      По причине
                    </Text>
                    <BreakdownList
                      items={fallbacks.data.by_reason}
                      labeler={(key) => FALLBACK_REASON_LABELS[key] ?? key}
                    />
                  </Stack>
                  <Stack gap="xs">
                    <Text size="sm" fw={600}>
                      По сервису
                    </Text>
                    <BreakdownList items={fallbacks.data.by_service} />
                  </Stack>
                </SimpleGrid>
              ) : (
                <Text size="sm" c="dimmed">
                  Данных нет
                </Text>
              )}
            </Stack>
          </Paper>
        </Stack>
      </div>
    </Stack>
  );
}
