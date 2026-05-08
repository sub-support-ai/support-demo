import {
  Alert,
  Badge,
  Button,
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
import {
  useAIFallbacksStats,
  useFailedJobs,
  useRetryAIJob,
  useRetryKnowledgeEmbeddingJob,
  useStats,
} from "../api/stats";
import { useMe } from "../api/auth";
import type { AIJob, KnowledgeEmbeddingJob } from "../api/types";
import { getStatusLabel } from "../lib/ticketLabels";
import { useAuth } from "../stores/auth";

// Карта стабильных reason-кодов из AIFallbackEvent.reason на UI-подписи.
// Любой неизвестный код проходит через as-is (см. BreakdownList): админ
// заметит «новую» причину в списке, мы добавим перевод в этот словарь
// без релиза фронта.
const FALLBACK_REASON_LABELS: Record<string, string> = {
  timeout: "Таймаут",
  connect: "Не достучались",
  http_5xx: "Ошибка HTTP",
  broken_json: "Битый JSON",
  empty_response: "Пустой ответ",
};

// service: где именно упало — чат /ai/answer или классификация /ai/classify.
const FALLBACK_SERVICE_LABELS: Record<string, string> = {
  answer: "Ответы в чате",
  classify: "Классификация тикетов",
};

function percent(value: number): string {
  return `${Math.round(value)}%`;
}

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

function formatDate(value?: string | null): string {
  if (!value) return "нет даты";
  return new Date(value).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function JobFailureRow({
  label,
  details,
  error,
  attempts,
  maxAttempts,
  finishedAt,
  onRetry,
  retrying,
}: {
  label: string;
  details: string;
  error?: string | null;
  attempts: number;
  maxAttempts: number;
  finishedAt?: string | null;
  onRetry: () => void;
  retrying: boolean;
}) {
  return (
    <Paper className="job-failure-row" withBorder>
      <Group justify="space-between" align="flex-start" gap="md">
        <Stack gap={4} className="job-failure-body">
          <Group gap="xs">
            <Badge color="red" variant="light">
              {label}
            </Badge>
            <Text size="sm" fw={700}>
              {details}
            </Text>
          </Group>
          <Text size="sm" c="dimmed">
            попыток: {attempts}/{maxAttempts} · завершено: {formatDate(finishedAt)}
          </Text>
          {error && (
            <Text size="sm" c="red" lineClamp={2}>
              {error}
            </Text>
          )}
        </Stack>
        <Button size="xs" variant="light" onClick={onRetry} loading={retrying}>
          Повторить
        </Button>
      </Group>
    </Paper>
  );
}

export function DashboardPage() {
  const { token } = useAuth();
  const { data: me } = useMe(Boolean(token));
  const stats = useStats();
  const data = stats.data;
  const isAdmin = me?.role === "admin";
  const failedJobs = useFailedJobs(isAdmin);
  const aiFallbacks = useAIFallbacksStats(isAdmin);
  const retryAIJob = useRetryAIJob();
  const retryKnowledgeJob = useRetryKnowledgeEmbeddingJob();
  const activeRequests =
    (data?.tickets.by_status.confirmed ?? 0) +
    (data?.tickets.by_status.in_progress ?? 0) +
    (data?.tickets.by_status.ai_processing ?? 0);

  return (
    <div className="content-page dashboard-page">
      <Paper className="tickets-panel dashboard-panel" withBorder>
        <LoadingOverlay visible={stats.isLoading} />
        <div className="dashboard-header">
          <div>
            <Title order={2}>Обзор</Title>
            <Text size="sm" c="dimmed">
              Живая статистика по запросам, SLA, маршрутизации и качеству ответов.
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
              <MetricCard label="Активно" value={activeRequests} />
              <MetricCard
                label="SLA просрочен"
                value={data.tickets.sla_overdue_count}
                hint="открытые запросы"
                tone={data.tickets.sla_overdue_count > 0 ? "warning" : "success"}
              />
              <MetricCard
                label="SLA эскалаций"
                value={data.tickets.sla_escalated_count}
                tone={data.tickets.sla_escalated_count > 0 ? "warning" : "neutral"}
              />
              <MetricCard
                label="Очередь AI"
                value={`${data.jobs.ai.queued} / ${data.jobs.ai.running}`}
                hint={`ошибок: ${data.jobs.ai.failed}`}
                tone={data.jobs.ai.failed > 0 ? "warning" : "neutral"}
              />
              <MetricCard
                label="Очередь RAG"
                value={`${data.jobs.knowledge_embeddings.queued} / ${data.jobs.knowledge_embeddings.running}`}
                hint={`ошибок: ${data.jobs.knowledge_embeddings.failed}`}
                tone={
                  data.jobs.knowledge_embeddings.failed > 0 ? "warning" : "neutral"
                }
              />
              <MetricCard
                label="Повторно открыто"
                value={data.tickets.reopen_count}
              />
              <MetricCard
                label="Обработано"
                value={data.ai.total_processed}
                hint="записей в журнале"
              />
              <MetricCard
                label="Низкая уверенность"
                value={data.ai.low_confidence_count}
                hint="требуют проверки"
              />
              <MetricCard
                label="Роутинг"
                value={percent(data.ai.routing_accuracy_pct)}
                hint="подтверждено агентами"
              />
            </SimpleGrid>

            {isAdmin && (
              <Paper className="quiet-panel dashboard-section" withBorder>
                <Group justify="space-between" mb="sm">
                  <div>
                    <Title order={4}>Ошибки фоновых задач</Title>
                    <Text size="sm" c="dimmed">
                      Последние сбои AI-ответов и индексации базы знаний.
                    </Text>
                  </div>
                  <Button
                    size="xs"
                    variant="subtle"
                    onClick={() => failedJobs.refetch()}
                    loading={failedJobs.isFetching}
                  >
                    Обновить
                  </Button>
                </Group>

                {failedJobs.error && (
                  <Alert color="red" variant="light" mb="sm">
                    {getApiError(failedJobs.error)}
                  </Alert>
                )}

                <Stack gap="sm">
                  {failedJobs.data?.ai.map((job: AIJob) => (
                    <JobFailureRow
                      key={`ai-${job.id}`}
                      label="AI"
                      details={`диалог #${job.conversation_id}, задача #${job.id}`}
                      error={job.error}
                      attempts={job.attempts}
                      maxAttempts={job.max_attempts}
                      finishedAt={job.finished_at}
                      retrying={retryAIJob.isPending}
                      onRetry={() => retryAIJob.mutate(job.id)}
                    />
                  ))}
                  {failedJobs.data?.knowledge_embeddings.map(
                    (job: KnowledgeEmbeddingJob) => (
                      <JobFailureRow
                        key={`knowledge-${job.id}`}
                        label="RAG"
                        details={
                          job.article_id
                            ? `статья #${job.article_id}, задача #${job.id}`
                            : `полный reindex, задача #${job.id}`
                        }
                        error={job.error}
                        attempts={job.attempts}
                        maxAttempts={job.max_attempts}
                        finishedAt={job.finished_at}
                        retrying={retryKnowledgeJob.isPending}
                        onRetry={() => retryKnowledgeJob.mutate(job.id)}
                      />
                    ),
                  )}
                  {!failedJobs.isLoading &&
                    failedJobs.data?.ai.length === 0 &&
                    failedJobs.data.knowledge_embeddings.length === 0 && (
                      <Text size="sm" c="dimmed">
                        Ошибок фоновых задач нет.
                      </Text>
                    )}
                </Stack>
              </Paper>
            )}

            {isAdmin && (
              <Paper className="quiet-panel dashboard-section" withBorder>
                <Group justify="space-between" mb="sm">
                  <div>
                    <Title order={4}>Сбои AI за 24 часа</Title>
                    <Text size="sm" c="dimmed">
                      Сколько раз AI-сервис ушёл в fallback и по какой причине.
                      Помогает отличить «модель отдала мусор» от «сервис не
                      отвечает» — каждый сбой требует разного действия.
                    </Text>
                  </div>
                  <Badge
                    size="lg"
                    variant="light"
                    color={
                      (aiFallbacks.data?.total ?? 0) === 0 ? "green" : "yellow"
                    }
                  >
                    Всего: {aiFallbacks.data?.total ?? 0}
                  </Badge>
                </Group>

                {aiFallbacks.error && (
                  <Alert color="red" variant="light" mb="sm">
                    {getApiError(aiFallbacks.error)}
                  </Alert>
                )}

                {aiFallbacks.data && aiFallbacks.data.total === 0 ? (
                  <Text size="sm" c="dimmed">
                    Сбоев нет — за 24 часа AI отвечал стабильно.
                  </Text>
                ) : (
                  <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
                    <div>
                      <Text size="xs" tt="uppercase" fw={700} c="dimmed" mb="xs">
                        По причинам
                      </Text>
                      <BreakdownList
                        items={aiFallbacks.data?.by_reason ?? {}}
                        labeler={(key) => FALLBACK_REASON_LABELS[key] ?? key}
                      />
                    </div>
                    <div>
                      <Text size="xs" tt="uppercase" fw={700} c="dimmed" mb="xs">
                        По источникам
                      </Text>
                      <BreakdownList
                        items={aiFallbacks.data?.by_service ?? {}}
                        labeler={(key) => FALLBACK_SERVICE_LABELS[key] ?? key}
                      />
                    </div>
                  </SimpleGrid>
                )}
              </Paper>
            )}

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
                tone="success"
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
