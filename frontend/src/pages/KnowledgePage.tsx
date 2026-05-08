import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Grid,
  Group,
  LoadingOverlay,
  Paper,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
  Title,
  Tooltip,
} from "@mantine/core";
import { IconDatabaseSearch, IconRefresh, IconSettings } from "@tabler/icons-react";
import { useEffect, useMemo, useState } from "react";

import { getApiError } from "../api/client";
import {
  useCreateKnowledgeArticle,
  useKnowledgeArticles,
  useReindexAllKnowledgeArticles,
  useReindexKnowledgeArticle,
  useUpdateKnowledgeArticle,
} from "../api/knowledge";
import type { KnowledgeArticle, KnowledgeArticlePayload } from "../api/types";

const departmentOptions = [
  { value: "IT", label: "IT" },
  { value: "HR", label: "HR" },
  { value: "finance", label: "finance" },
];

const scopeOptions = [
  { value: "public", label: "Публичная" },
  { value: "internal", label: "Внутренняя" },
];

type KnowledgeFormState = {
  department: "IT" | "HR" | "finance" | "";
  request_type: string;
  title: string;
  body: string;
  problem: string;
  symptoms: string;
  steps: string;
  when_to_escalate: string;
  required_context: string;
  keywords: string;
  source_url: string;
  owner: string;
  access_scope: "public" | "internal";
  is_active: boolean;
};

// «Полезность» статьи: процент полезных ответов из всех оценок + сырой
// разбивкой в tooltip. Считаем здесь, а не в формуле пользователя глазами:
//
//   helped       — пользователь отметил «помогло»
//   not_helped   — статья нашлась, но не помогла (контент устарел / неполный)
//   not_relevant — статья не подходила к запросу (RAG ошибся, не контент)
//
// Без not_relevant в показе админ не увидит проблем поиска и будет винить
// автора статьи; поэтому tooltip показывает все три цифры явно.
type FeedbackStats = {
  total: number;
  helpedRatio: number; // 0..1, NaN если total==0
};

function summarizeFeedback(article: KnowledgeArticle): FeedbackStats {
  const total =
    article.helped_count + article.not_helped_count + article.not_relevant_count;
  return {
    total,
    helpedRatio: total === 0 ? Number.NaN : article.helped_count / total,
  };
}

function feedbackBadgeColor(ratio: number, total: number): string {
  if (total === 0) return "gray";
  if (ratio >= 0.7) return "green";
  if (ratio >= 0.4) return "yellow";
  return "red";
}

const emptyForm: KnowledgeFormState = {
  department: "",
  request_type: "",
  title: "",
  body: "",
  problem: "",
  symptoms: "",
  steps: "",
  when_to_escalate: "",
  required_context: "",
  keywords: "",
  source_url: "",
  owner: "",
  access_scope: "public",
  is_active: true,
};

function listFromLines(value: string): string[] | null {
  const items = value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
  return items.length ? items : null;
}

function joinLines(value?: string[] | null): string {
  return value?.join("\n") ?? "";
}

function formFromArticle(article: KnowledgeArticle): KnowledgeFormState {
  return {
    department: article.department ?? "",
    request_type: article.request_type ?? "",
    title: article.title,
    body: article.body,
    problem: article.problem ?? "",
    symptoms: joinLines(article.symptoms),
    steps: joinLines(article.steps),
    when_to_escalate: article.when_to_escalate ?? "",
    required_context: joinLines(article.required_context),
    keywords: article.keywords ?? "",
    source_url: article.source_url ?? "",
    owner: article.owner ?? "",
    access_scope: article.access_scope,
    is_active: article.is_active,
  };
}

function payloadFromForm(form: KnowledgeFormState): KnowledgeArticlePayload {
  return {
    department: form.department || null,
    request_type: form.request_type.trim() || null,
    title: form.title,
    body: form.body,
    problem: form.problem.trim() || null,
    symptoms: listFromLines(form.symptoms),
    steps: listFromLines(form.steps),
    when_to_escalate: form.when_to_escalate.trim() || null,
    required_context: listFromLines(form.required_context),
    keywords: form.keywords.trim() || null,
    source_url: form.source_url.trim() || null,
    owner: form.owner.trim() || null,
    access_scope: form.access_scope,
    is_active: form.is_active,
  };
}

export function KnowledgePage() {
  const articles = useKnowledgeArticles(false);
  const createArticle = useCreateKnowledgeArticle();
  const updateArticle = useUpdateKnowledgeArticle();
  const reindexArticle = useReindexKnowledgeArticle();
  const reindexAllArticles = useReindexAllKnowledgeArticles();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [form, setForm] = useState<KnowledgeFormState>(emptyForm);

  const selectedArticle = useMemo(
    () => articles.data?.find((article) => article.id === selectedId) ?? null,
    [articles.data, selectedId],
  );

  useEffect(() => {
    if (selectedArticle) {
      setForm(formFromArticle(selectedArticle));
    }
  }, [selectedArticle]);

  const error =
    articles.error ||
    createArticle.error ||
    updateArticle.error ||
    reindexArticle.error ||
    reindexAllArticles.error;

  function patchForm(update: Partial<KnowledgeFormState>) {
    setForm((current) => ({ ...current, ...update }));
  }

  async function handleSave() {
    const payload = payloadFromForm(form);
    if (selectedArticle) {
      const article = await updateArticle.mutateAsync({
        articleId: selectedArticle.id,
        payload,
      });
      setSelectedId(article.id);
      return;
    }

    const article = await createArticle.mutateAsync(payload);
    setSelectedId(article.id);
  }

  async function handleReindex() {
    if (!selectedArticle) {
      return;
    }
    await reindexArticle.mutateAsync(selectedArticle.id);
  }

  return (
    <div className="content-page knowledge-page">
      <Paper className="dashboard-panel" withBorder>
        <Group justify="space-between" mb="lg" align="start">
          <div>
            <Title order={2}>База знаний</Title>
            <Text size="sm" c="dimmed">
              Статьи, которые участвуют в поиске, ответах и эскалации.
            </Text>
          </div>
          <Button
            variant="light"
            leftSection={<IconDatabaseSearch size={16} />}
            onClick={() => {
              setSelectedId(null);
              setForm(emptyForm);
            }}
          >
            Новая статья
          </Button>
          <Button
            variant="light"
            leftSection={<IconRefresh size={16} />}
            loading={reindexAllArticles.isPending}
            onClick={() => reindexAllArticles.mutate()}
          >
            Reindex all
          </Button>
        </Group>

        {error && (
          <Alert color="red" variant="light" mb="md">
            {getApiError(error)}
          </Alert>
        )}

        <Grid align="stretch">
          <Grid.Col span={{ base: 12, lg: 5 }}>
            <Paper withBorder className="knowledge-list-panel">
              <LoadingOverlay visible={articles.isLoading} />
              <Table verticalSpacing="sm" highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Статья</Table.Th>
                    <Table.Th>Статус</Table.Th>
                    <Table.Th>Оценка</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {articles.data?.map((article) => (
                    <Table.Tr
                      key={article.id}
                      className={
                        article.id === selectedId ? "knowledge-row active" : "knowledge-row"
                      }
                      onClick={() => setSelectedId(article.id)}
                    >
                      <Table.Td>
                        <Text fw={600} size="sm" lineClamp={1}>
                          {article.title}
                        </Text>
                        <Text size="xs" c="dimmed" lineClamp={1}>
                          {[article.department, article.request_type, article.owner]
                            .filter(Boolean)
                            .join(" · ") || "Без привязки"}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Badge
                          size="sm"
                          color={article.is_active ? "green" : "gray"}
                          variant="light"
                        >
                          {article.is_active ? "Активна" : "Выключена"}
                        </Badge>
                      </Table.Td>
                      <Table.Td>
                        {(() => {
                          const stats = summarizeFeedback(article);
                          if (stats.total === 0) {
                            return (
                              <Text size="xs" c="dimmed">
                                нет оценок
                              </Text>
                            );
                          }
                          const percent = Math.round(stats.helpedRatio * 100);
                          return (
                            <Tooltip
                              withArrow
                              label={
                                `Помогло: ${article.helped_count}` +
                                ` · Не помогло: ${article.not_helped_count}` +
                                ` · Не подошло: ${article.not_relevant_count}`
                              }
                            >
                              <Badge
                                size="sm"
                                variant="light"
                                color={feedbackBadgeColor(stats.helpedRatio, stats.total)}
                              >
                                {percent}% · {stats.total}
                              </Badge>
                            </Tooltip>
                          );
                        })()}
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Paper>
          </Grid.Col>

          <Grid.Col span={{ base: 12, lg: 7 }}>
            <Paper withBorder className="knowledge-editor-panel">
              <Stack gap="sm">
                <Group justify="space-between">
                  <Title order={3}>
                    {selectedArticle ? "Редактирование" : "Новая статья"}
                  </Title>
                  {selectedArticle && (
                    <Button
                      variant="subtle"
                      leftSection={<IconRefresh size={16} />}
                      loading={reindexArticle.isPending}
                      onClick={handleReindex}
                    >
                      Reindex
                    </Button>
                  )}
                </Group>

                <Grid>
                  <Grid.Col span={{ base: 12, sm: 6 }}>
                    <Select
                      label="Отдел"
                      placeholder="Любой"
                      data={departmentOptions}
                      clearable
                      value={form.department || null}
                      onChange={(value) =>
                        patchForm({
                          department: (value as KnowledgeFormState["department"]) ?? "",
                        })
                      }
                    />
                  </Grid.Col>
                  <Grid.Col span={{ base: 12, sm: 6 }}>
                    <TextInput
                      label="Тип запроса"
                      value={form.request_type}
                      onChange={(event) =>
                        patchForm({ request_type: event.currentTarget.value })
                      }
                    />
                  </Grid.Col>
                </Grid>

                <TextInput
                  label="Заголовок"
                  required
                  value={form.title}
                  onChange={(event) => patchForm({ title: event.currentTarget.value })}
                />
                <Textarea
                  label="Проблема"
                  minRows={2}
                  value={form.problem}
                  onChange={(event) =>
                    patchForm({ problem: event.currentTarget.value })
                  }
                />
                <Textarea
                  label="Основной текст"
                  required
                  minRows={5}
                  value={form.body}
                  onChange={(event) => patchForm({ body: event.currentTarget.value })}
                />
                <Textarea
                  label="Симптомы"
                  minRows={3}
                  value={form.symptoms}
                  onChange={(event) =>
                    patchForm({ symptoms: event.currentTarget.value })
                  }
                />
                <Textarea
                  label="Шаги решения"
                  minRows={4}
                  value={form.steps}
                  onChange={(event) => patchForm({ steps: event.currentTarget.value })}
                />
                <Textarea
                  label="Когда эскалировать"
                  minRows={2}
                  value={form.when_to_escalate}
                  onChange={(event) =>
                    patchForm({ when_to_escalate: event.currentTarget.value })
                  }
                />
                <Textarea
                  label="Что уточнить перед запросом"
                  minRows={3}
                  value={form.required_context}
                  onChange={(event) =>
                    patchForm({ required_context: event.currentTarget.value })
                  }
                />

                <Grid>
                  <Grid.Col span={{ base: 12, sm: 6 }}>
                    <TextInput
                      label="Ключевые слова"
                      value={form.keywords}
                      onChange={(event) =>
                        patchForm({ keywords: event.currentTarget.value })
                      }
                    />
                  </Grid.Col>
                  <Grid.Col span={{ base: 12, sm: 6 }}>
                    <TextInput
                      label="Владелец"
                      value={form.owner}
                      onChange={(event) =>
                        patchForm({ owner: event.currentTarget.value })
                      }
                    />
                  </Grid.Col>
                </Grid>

                <Grid align="end">
                  <Grid.Col span={{ base: 12, sm: 5 }}>
                    <TextInput
                      label="Источник"
                      value={form.source_url}
                      onChange={(event) =>
                        patchForm({ source_url: event.currentTarget.value })
                      }
                    />
                  </Grid.Col>
                  <Grid.Col span={{ base: 12, sm: 4 }}>
                    <Select
                      label="Доступ"
                      data={scopeOptions}
                      value={form.access_scope}
                      onChange={(value) =>
                        patchForm({
                          access_scope: (value as "public" | "internal") ?? "public",
                        })
                      }
                    />
                  </Grid.Col>
                  <Grid.Col span={{ base: 12, sm: 3 }}>
                    <Checkbox
                      label="Активна"
                      checked={form.is_active}
                      onChange={(event) =>
                        patchForm({ is_active: event.currentTarget.checked })
                      }
                    />
                  </Grid.Col>
                </Grid>

                <Group justify="flex-end">
                  {selectedArticle && (
                    <Text size="xs" c="dimmed">
                      Версия {selectedArticle.version} · просмотры{" "}
                      {selectedArticle.view_count}
                    </Text>
                  )}
                  <Button
                    leftSection={<IconSettings size={16} />}
                    loading={createArticle.isPending || updateArticle.isPending}
                    onClick={handleSave}
                  >
                    Сохранить
                  </Button>
                </Group>
              </Stack>
            </Paper>
          </Grid.Col>
        </Grid>
      </Paper>
    </div>
  );
}
