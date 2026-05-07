import {
  Alert,
  Badge,
  Button,
  Group,
  LoadingOverlay,
  Paper,
  Select,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { IconRefresh } from "@tabler/icons-react";
import { useState } from "react";

import { getApiError } from "../api/client";
import {
  useJobs,
  useRequeueAIJob,
  useRequeueKnowledgeEmbeddingJob,
  useRetryAIJob,
  useRetryKnowledgeEmbeddingJob,
} from "../api/stats";
import type {
  AIJob,
  JobKind,
  JobStatusFilter,
  KnowledgeEmbeddingJob,
} from "../api/types";
import { useMe } from "../api/auth";
import { useAuth } from "../stores/auth";

const kindOptions = [
  { value: "all", label: "Все очереди" },
  { value: "ai", label: "AI ответы" },
  { value: "knowledge_embeddings", label: "RAG индексация" },
];

const statusOptions = [
  { value: "all", label: "Все статусы" },
  { value: "queued", label: "В очереди" },
  { value: "running", label: "В работе" },
  { value: "done", label: "Готово" },
  { value: "failed", label: "Ошибка" },
];

type JobRow =
  | { kind: "ai"; job: AIJob }
  | { kind: "knowledge_embeddings"; job: KnowledgeEmbeddingJob };

const STALE_RUNNING_MINUTES = 5;

function statusColor(status: string): string {
  if (status === "failed") return "red";
  if (status === "running") return "blue";
  if (status === "done") return "green";
  return "gray";
}

function formatDate(value?: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function isStaleRunning(job: AIJob | KnowledgeEmbeddingJob): boolean {
  if (job.status !== "running" || !job.locked_at) {
    return false;
  }
  const lockedAt = new Date(job.locked_at).getTime();
  return Date.now() - lockedAt > STALE_RUNNING_MINUTES * 60 * 1000;
}

function jobTarget(row: JobRow): string {
  if (row.kind === "ai") {
    return `Диалог #${row.job.conversation_id}`;
  }
  return row.job.article_id ? `Статья #${row.job.article_id}` : "Полный reindex";
}

export function JobsPage() {
  const { token } = useAuth();
  const { data: me } = useMe(Boolean(token));
  const isAdmin = me?.role === "admin";
  const [kind, setKind] = useState<JobKind>("all");
  const [status, setStatus] = useState<JobStatusFilter>("all");
  const jobs = useJobs({ enabled: isAdmin, kind, status });
  const retryAIJob = useRetryAIJob();
  const requeueAIJob = useRequeueAIJob();
  const retryKnowledgeJob = useRetryKnowledgeEmbeddingJob();
  const requeueKnowledgeJob = useRequeueKnowledgeEmbeddingJob();

  const rows: JobRow[] = [
    ...(jobs.data?.ai.map((job) => ({ kind: "ai" as const, job })) ?? []),
    ...(jobs.data?.knowledge_embeddings.map((job) => ({
      kind: "knowledge_embeddings" as const,
      job,
    })) ?? []),
  ].sort((left, right) => right.job.id - left.job.id);

  if (!isAdmin) {
    return (
      <div className="content-page dashboard-page">
        <Alert color="red" variant="light">
          Раздел доступен только администратору.
        </Alert>
      </div>
    );
  }

  return (
    <div className="content-page jobs-page">
      <Paper className="dashboard-panel" withBorder>
        <Group justify="space-between" mb="lg" align="start">
          <div>
            <Title order={2}>Очереди задач</Title>
            <Text size="sm" c="dimmed">
              Состояние фоновой обработки AI-ответов и RAG-индексации.
            </Text>
          </div>
          <Button
            variant="light"
            leftSection={<IconRefresh size={16} />}
            loading={jobs.isFetching}
            onClick={() => jobs.refetch()}
          >
            Обновить
          </Button>
        </Group>

        <Group mb="md" align="end">
          <Select
            label="Очередь"
            data={kindOptions}
            value={kind}
            onChange={(value) => setKind((value as JobKind | null) ?? "all")}
          />
          <Select
            label="Статус"
            data={statusOptions}
            value={status}
            onChange={(value) =>
              setStatus((value as JobStatusFilter | null) ?? "all")
            }
          />
        </Group>

        {jobs.error && (
          <Alert color="red" variant="light" mb="md">
            {getApiError(jobs.error)}
          </Alert>
        )}

        <Paper className="jobs-table-panel" withBorder>
          <LoadingOverlay visible={jobs.isLoading} />
          <Table verticalSpacing="sm" highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Тип</Table.Th>
                <Table.Th>Цель</Table.Th>
                <Table.Th>Статус</Table.Th>
                <Table.Th>Попытки</Table.Th>
                <Table.Th>Запуск</Table.Th>
                <Table.Th>Ошибка</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((row) => (
                <Table.Tr key={`${row.kind}-${row.job.id}`}>
                  <Table.Td>
                    <Badge variant="light">
                      {row.kind === "ai" ? "AI" : "RAG"}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" fw={600}>
                      {jobTarget(row)}
                    </Text>
                    <Text size="xs" c="dimmed">
                      задача #{row.job.id}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Stack gap={4}>
                      <Badge color={statusColor(row.job.status)} variant="light">
                        {row.job.status}
                      </Badge>
                      {isStaleRunning(row.job) && (
                        <Badge color="orange" variant="light">
                          зависла
                        </Badge>
                      )}
                    </Stack>
                  </Table.Td>
                  <Table.Td>
                    {row.job.attempts}/{row.job.max_attempts}
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{formatDate(row.job.run_after)}</Text>
                    <Text size="xs" c="dimmed">
                      создана: {formatDate(row.job.created_at)}
                    </Text>
                    {row.job.locked_at && (
                      <Text size="xs" c="dimmed">
                        lock: {formatDate(row.job.locked_at)}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td className="jobs-error-cell">
                    <Text size="sm" c={row.job.error ? "red" : "dimmed"} lineClamp={2}>
                      {row.job.error || "-"}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap="xs" justify="flex-end">
                      {row.job.status === "failed" && (
                        <Button
                          size="xs"
                          variant="light"
                          loading={
                            row.kind === "ai"
                              ? retryAIJob.isPending
                              : retryKnowledgeJob.isPending
                          }
                          onClick={() => {
                            if (row.kind === "ai") {
                              retryAIJob.mutate(row.job.id, {
                                onSuccess: () => jobs.refetch(),
                              });
                              return;
                            }
                            retryKnowledgeJob.mutate(row.job.id, {
                              onSuccess: () => jobs.refetch(),
                            });
                          }}
                        >
                          Повторить
                        </Button>
                      )}
                      {isStaleRunning(row.job) && (
                        <Button
                          size="xs"
                          color="orange"
                          variant="light"
                          loading={
                            row.kind === "ai"
                              ? requeueAIJob.isPending
                              : requeueKnowledgeJob.isPending
                          }
                          onClick={() => {
                            if (row.kind === "ai") {
                              requeueAIJob.mutate(row.job.id, {
                                onSuccess: () => jobs.refetch(),
                              });
                              return;
                            }
                            requeueKnowledgeJob.mutate(row.job.id, {
                              onSuccess: () => jobs.refetch(),
                            });
                          }}
                        >
                          В очередь
                        </Button>
                      )}
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
              {!jobs.isLoading && rows.length === 0 && (
                <Table.Tr>
                  <Table.Td colSpan={7}>
                    <Text size="sm" c="dimmed" ta="center" py="md">
                      Задач по выбранным фильтрам нет.
                    </Text>
                  </Table.Td>
                </Table.Tr>
              )}
            </Table.Tbody>
          </Table>
        </Paper>
      </Paper>
    </div>
  );
}
