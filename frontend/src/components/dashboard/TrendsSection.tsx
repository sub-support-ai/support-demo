/**
 * Тренды по тикетам — линейный график создано/решено за период.
 *
 * Архитектурно — smart-компонент (сам ходит за данными), а не презентация.
 * Причина: данные нужны только этому виджету, поднимать загрузку выше = размывать
 * ответственность. Если потребуются эти же данные где-то ещё, React Query
 * автоматически переиспользует cache по ключу `["stats", "trends", periodDays]`.
 *
 * Период — `Select` 7/14/30/90 дней. По умолчанию 30 — это окно «месяца», по
 * которому обычно строят отчёты для менеджмента; короче 30 — оперативный
 * мониторинг, 90 — квартальный взгляд.
 */

import { LineChart } from "@mantine/charts";
import {
  Alert,
  Badge,
  Group,
  Loader,
  Paper,
  Select,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useMemo, useState } from "react";

import { getApiError } from "../../api/client";
import { useStatsTrends } from "../../api/stats";

const PERIOD_OPTIONS = [
  { value: "7", label: "7 дней" },
  { value: "14", label: "14 дней" },
  { value: "30", label: "30 дней" },
  { value: "90", label: "90 дней" },
];

/** Сжимаем `2026-05-15` до `15.05` для оси X — длинные даты не помещаются. */
function shortDate(iso: string): string {
  const parts = iso.split("-");
  if (parts.length !== 3) return iso;
  return `${parts[2]}.${parts[1]}`;
}

/** Объединяет две серии в один массив точек — формат, который ожидает LineChart. */
function buildChartData(
  created: ReadonlyArray<{ date: string; count: number }>,
  resolved: ReadonlyArray<{ date: string; count: number }>,
): Array<{ date: string; created: number; resolved: number }> {
  // Делаем индекс по дате — бэкенд гарантирует, что в обеих сериях
  // одинаковый набор дат, но строим map для устойчивости к расхождениям.
  const resolvedMap = new Map(resolved.map((p) => [p.date, p.count]));
  return created.map((p) => ({
    date: shortDate(p.date),
    created: p.count,
    resolved: resolvedMap.get(p.date) ?? 0,
  }));
}

export function TrendsSection() {
  const [period, setPeriod] = useState<string>("30");
  const periodDays = Number(period);

  const query = useStatsTrends({ periodDays, enabled: true });
  const data = query.data;

  // Чарт-данные пересчитываем только при изменении ответа,
  // не на каждом ре-рендере родителя.
  const chartData = useMemo(
    () => (data ? buildChartData(data.tickets_created, data.tickets_resolved) : []),
    [data],
  );

  // Сводка под графиком — даёт быстрый ответ «а сколько вообще?»,
  // без необходимости считать столбики глазами.
  const totals = useMemo(() => {
    if (!data) return null;
    const created = data.tickets_created.reduce((sum, p) => sum + p.count, 0);
    const resolved = data.tickets_resolved.reduce((sum, p) => sum + p.count, 0);
    const ratio = created > 0 ? Math.round((resolved / created) * 100) : 0;
    return { created, resolved, ratio };
  }, [data]);

  const hasAnyData = totals !== null && (totals.created > 0 || totals.resolved > 0);

  return (
    <Paper className="quiet-panel dashboard-section" withBorder p="md">
      <Group justify="space-between" mb="sm" align="flex-end" wrap="wrap" gap="sm">
        <div>
          <Title order={4}>Тренды по тикетам</Title>
          <Text size="sm" c="dimmed">
            Создание и решение запросов в динамике.
          </Text>
        </div>
        <Select
          data={PERIOD_OPTIONS}
          value={period}
          onChange={(value) => value && setPeriod(value)}
          allowDeselect={false}
          w={140}
          aria-label="Период тренда"
        />
      </Group>

      {query.error && (
        <Alert color="red" variant="light" mb="sm">
          {getApiError(query.error)}
        </Alert>
      )}

      {query.isLoading && !data ? (
        <Group justify="center" p="lg">
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            Загружаем тренды…
          </Text>
        </Group>
      ) : !hasAnyData ? (
        <Text size="sm" c="dimmed" ta="center" py="xl">
          За выбранный период тикетов не было.
        </Text>
      ) : (
        <Stack gap="sm">
          <LineChart
            h={260}
            data={chartData}
            dataKey="date"
            series={[
              { name: "created", color: "blue.6", label: "Создано" },
              { name: "resolved", color: "teal.6", label: "Решено" },
            ]}
            curveType="monotone"
            withLegend
            withDots={chartData.length <= 14}
            tickLine="xy"
            gridAxis="xy"
            yAxisProps={{ allowDecimals: false }}
          />
          {totals && (
            <Group gap="md" wrap="wrap">
              <Badge color="blue" variant="light" size="lg">
                Создано: {totals.created}
              </Badge>
              <Badge color="teal" variant="light" size="lg">
                Решено: {totals.resolved}
              </Badge>
              <Badge
                color={totals.ratio >= 80 ? "teal" : totals.ratio >= 50 ? "yellow" : "orange"}
                variant="light"
                size="lg"
              >
                Решено / создано: {totals.ratio}%
              </Badge>
            </Group>
          )}
        </Stack>
      )}
    </Paper>
  );
}
