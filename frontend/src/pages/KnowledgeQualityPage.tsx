import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  Stack,
  Table,
  Tabs,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconClockExclamation,
  IconEye,
  IconMessageQuestion,
  IconPlus,
  IconRefresh,
  IconThumbDown,
} from "@tabler/icons-react";

import { getApiError } from "../api/client";
import { useKBQualityStats } from "../api/stats";
import type { KBArticleQualityItem, UnansweredQuery } from "../api/types";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function daysUntil(iso: string | null): number | null {
  if (!iso) return null;
  const diff = new Date(iso).getTime() - Date.now();
  return Math.ceil(diff / 86400000);
}

function HelpRatioBadge({ ratio, total }: { ratio: number | null; total: number }) {
  if (total === 0 || ratio === null) return <Text size="xs" c="dimmed">нет оценок</Text>;
  const pct = Math.round(ratio * 100);
  const color = pct >= 70 ? "green" : pct >= 40 ? "yellow" : "red";
  return (
    <Badge size="sm" color={color} variant="light">
      {pct}% · {total} оц.
    </Badge>
  );
}

function ArticleRow({
  article,
  onCreateArticle,
  showExpiry,
}: {
  article: KBArticleQualityItem;
  onCreateArticle: (title: string) => void;
  showExpiry?: boolean;
}) {
  const total = article.helped_count + article.not_helped_count + article.not_relevant_count;
  const days = showExpiry ? daysUntil(article.expires_at) : null;

  return (
    <Table.Tr>
      <Table.Td>
        <Text size="sm" fw={500} lineClamp={1}>{article.title}</Text>
        {article.department && (
          <Badge size="xs" variant="dot" color="gray" mt={2}>{article.department}</Badge>
        )}
      </Table.Td>
      <Table.Td>
        <Text size="xs" c="dimmed">{article.view_count} показов</Text>
      </Table.Td>
      <Table.Td>
        <HelpRatioBadge ratio={article.helpfulness_ratio} total={total} />
      </Table.Td>
      {showExpiry && (
        <Table.Td>
          {days !== null && (
            <Badge size="sm" color={days <= 3 ? "red" : days <= 7 ? "orange" : "yellow"} variant="light">
              через {days} д.
            </Badge>
          )}
        </Table.Td>
      )}
      <Table.Td>
        <Button
          size="xs"
          variant="subtle"
          leftSection={<IconPlus size={12} />}
          onClick={() => onCreateArticle(article.title)}
        >
          Улучшить
        </Button>
      </Table.Td>
    </Table.Tr>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <Text size="sm" c="dimmed" ta="center" py="xl">
      {message}
    </Text>
  );
}

interface Props {
  onCreateArticle: (prefillTitle?: string) => void;
}

export function KnowledgeQualityPage({ onCreateArticle }: Props) {
  const quality = useKBQualityStats(true);

  if (quality.isLoading) {
    return (
      <Stack align="center" py="xl">
        <Loader size="sm" />
        <Text size="sm" c="dimmed">Загрузка данных качества KB…</Text>
      </Stack>
    );
  }

  if (quality.error) {
    return (
      <Alert color="red" variant="light">
        {getApiError(quality.error)}
      </Alert>
    );
  }

  const data = quality.data!;
  const totalIssues =
    data.not_helping.length + data.never_shown.length + data.expiring_soon.length;

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <div>
          <Title order={3}>Качество базы знаний</Title>
          <Text size="sm" c="dimmed">
            {totalIssues > 0
              ? `${totalIssues} проблем требуют внимания`
              : "Всё в порядке — проблем не обнаружено"}
          </Text>
        </div>
        <Group gap="xs">
          <Button
            size="xs"
            variant="subtle"
            leftSection={<IconRefresh size={14} />}
            loading={quality.isFetching}
            onClick={() => quality.refetch()}
          >
            Обновить
          </Button>
          <Button
            size="xs"
            leftSection={<IconPlus size={14} />}
            onClick={() => onCreateArticle()}
          >
            Новая статья
          </Button>
        </Group>
      </Group>

      <Tabs defaultValue="not_helping">
        <Tabs.List>
          <Tabs.Tab
            value="not_helping"
            leftSection={<IconThumbDown size={14} />}
            color="red"
          >
            Не помогают
            {data.not_helping.length > 0 && (
              <Badge size="xs" color="red" variant="filled" ml={6}>
                {data.not_helping.length}
              </Badge>
            )}
          </Tabs.Tab>
          <Tabs.Tab
            value="never_shown"
            leftSection={<IconEye size={14} />}
            color="orange"
          >
            Не показывались
            {data.never_shown.length > 0 && (
              <Badge size="xs" color="orange" variant="filled" ml={6}>
                {data.never_shown.length}
              </Badge>
            )}
          </Tabs.Tab>
          <Tabs.Tab
            value="expiring"
            leftSection={<IconClockExclamation size={14} />}
            color="yellow"
          >
            Устаревают
            {data.expiring_soon.length > 0 && (
              <Badge size="xs" color="yellow" variant="filled" ml={6}>
                {data.expiring_soon.length}
              </Badge>
            )}
          </Tabs.Tab>
          <Tabs.Tab
            value="unanswered"
            leftSection={<IconMessageQuestion size={14} />}
            color="blue"
          >
            Без ответа
            {data.unanswered_queries.length > 0 && (
              <Badge size="xs" color="blue" variant="filled" ml={6}>
                {data.unanswered_queries.length}
              </Badge>
            )}
          </Tabs.Tab>
        </Tabs.List>

        {/* Не помогают */}
        <Tabs.Panel value="not_helping" pt="md">
          <Text size="xs" c="dimmed" mb="sm">
            Статьи, у которых «не помогло» + «не по теме» превышает «помогло» при
            не менее 3 оценках. Требуют доработки или замены.
          </Text>
          {data.not_helping.length === 0 ? (
            <EmptyState message="Статей с плохой обратной связью нет — отлично!" />
          ) : (
            <Table verticalSpacing="sm" highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Статья</Table.Th>
                  <Table.Th>Показы</Table.Th>
                  <Table.Th>Полезность</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {data.not_helping.map((a) => (
                  <ArticleRow key={a.id} article={a} onCreateArticle={onCreateArticle} />
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Tabs.Panel>

        {/* Не показывались */}
        <Tabs.Panel value="never_shown" pt="md">
          <Text size="xs" c="dimmed" mb="sm">
            Активные статьи, которые ни разу не попали в результаты поиска. Возможно,
            плохие ключевые слова или дублирование с другой статьёй.
          </Text>
          {data.never_shown.length === 0 ? (
            <EmptyState message="Все активные статьи хотя бы раз показывались" />
          ) : (
            <Table verticalSpacing="sm" highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Статья</Table.Th>
                  <Table.Th>Показы</Table.Th>
                  <Table.Th>Полезность</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {data.never_shown.map((a) => (
                  <ArticleRow key={a.id} article={a} onCreateArticle={onCreateArticle} />
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Tabs.Panel>

        {/* Устаревают */}
        <Tabs.Panel value="expiring" pt="md">
          <Text size="xs" c="dimmed" mb="sm">
            Статьи, срок проверки которых истекает в ближайшие 14 дней. Проверьте
            актуальность содержимого и обновите дату ревью.
          </Text>
          {data.expiring_soon.length === 0 ? (
            <EmptyState message="Нет статей с истекающим сроком проверки" />
          ) : (
            <Table verticalSpacing="sm" highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Статья</Table.Th>
                  <Table.Th>Показы</Table.Th>
                  <Table.Th>Полезность</Table.Th>
                  <Table.Th>Истекает</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {data.expiring_soon.map((a) => (
                  <ArticleRow
                    key={a.id}
                    article={a}
                    onCreateArticle={onCreateArticle}
                    showExpiry
                  />
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Tabs.Panel>

        {/* Без ответа */}
        <Tabs.Panel value="unanswered" pt="md">
          <Text size="xs" c="dimmed" mb="sm">
            Запросы из эскалированных диалогов — пользователи не получили ответа из KB.
            Каждый пункт — потенциальная новая статья.
          </Text>
          {data.unanswered_queries.length === 0 ? (
            <EmptyState message="Неотвеченных запросов не найдено" />
          ) : (
            <Table verticalSpacing="sm" highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Запрос</Table.Th>
                  <Table.Th>Частота</Table.Th>
                  <Table.Th>Последний раз</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {data.unanswered_queries.map((q: UnansweredQuery, i) => (
                  <Table.Tr key={i}>
                    <Table.Td>
                      <Tooltip label={q.query} multiline maw={400} withArrow>
                        <Text size="sm" lineClamp={2} style={{ maxWidth: 420 }}>
                          {q.query}
                        </Text>
                      </Tooltip>
                    </Table.Td>
                    <Table.Td>
                      <Badge size="sm" variant="light" color="blue">
                        {q.count}×
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" c="dimmed">{formatDate(q.last_seen)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Button
                        size="xs"
                        variant="subtle"
                        leftSection={<IconPlus size={12} />}
                        onClick={() => onCreateArticle(q.query)}
                      >
                        Создать статью
                      </Button>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Tabs.Panel>
      </Tabs>

      {data.unanswered_queries.length > 0 && (
        <Alert
          icon={<IconAlertTriangle size={16} />}
          color="blue"
          variant="light"
          title="Как использовать эти данные"
        >
          Нажмите «Создать статью» рядом с любым запросом — откроется форма с
          предзаполненным заголовком. Добавьте решение, ключевые слова и сохраните.
          После переиндексации статья начнёт участвовать в поиске.
        </Alert>
      )}
    </Stack>
  );
}
