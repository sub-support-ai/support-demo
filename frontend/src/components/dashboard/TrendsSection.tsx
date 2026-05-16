/**
 * Тренды по тикетам — линейный график создано/решено за календарный месяц.
 *
 * Навигация: кнопки «‹» / «›» листают месяцы. Текущий месяц — максимум
 * (кнопка «›» задизейблена). Назад — до 24 месяцев.
 *
 * Данные: GET /stats/trends?since=YYYY-MM-DD&until=YYYY-MM-DD.
 * React Query кэширует каждый месяц от��ельно (ключ включает since+until).
 */

import { LineChart } from "@mantine/charts";
import {
  ActionIcon,
  Alert,
  Badge,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconChevronLeft, IconChevronRight } from "@tabler/icons-react";
import { useMemo, useState } from "react";

import { getApiError } from "../../api/client";
import { useStatsTrends } from "../../api/stats";

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
  const resolvedMap = new Map(resolved.map((p) => [p.date, p.count]));
  return created.map((p) => ({
    date: shortDate(p.date),
    created: p.count,
    resolved: resolvedMap.get(p.date) ?? 0,
  }));
}

/** «Май 2026» — заголовок месяца с заглавной буквы. */
function formatMonthTitle(year: number, month: number): string {
  const s = new Date(year, month - 1, 1).toLocaleDateString("ru-RU", {
    month: "long",
    year: "numeric",
  });
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** «1 мая — 31 мая 2026» — подпись диапазона под навигатором. */
function formatMonthRange(year: number, month: number): string {
  const first = new Date(year, month - 1, 1);
  const last = new Date(year, month, 0);
  const from = first.toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
  const to = last.toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
  return `${from} — ${to}`;
}

export function TrendsSection() {
  const today = new Date();

  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1); // 1–12

  const isCurrentMonth =
    year === today.getFullYear() && month === today.getMonth() + 1;

  // Ограничение: не дальше 24 месяцев назад
  const minYear = today.getFullYear() - 2;
  const minMonth = today.getMonth() + 1; // тот же месяц, 2 года назад
  const isMinMonth =
    year < minYear || (year === minYear && month <= minMonth);

  function prevMonth() {
    if (isMinMonth) return;
    if (month === 1) {
      setYear((y) => y - 1);
      setMonth(12);
    } else {
      setMonth((m) => m - 1);
    }
  }

  function nextMonth() {
    if (isCurrentMonth) return;
    if (month === 12) {
      setYear((y) => y + 1);
      setMonth(1);
    } else {
      setMonth((m) => m + 1);
    }
  }

  const daysInMonth = new Date(year, month, 0).getDate();
  const since = `${year}-${String(month).padStart(2, "0")}-01`;
  const until = `${year}-${String(month).padStart(2, "0")}-${String(daysInMonth).padStart(2, "0")}`;

  const query = useStatsTrends({ since, until, enabled: true });
  const data = query.data;

  const chartData = useMemo(
    () => (data ? buildChartData(data.tickets_created, data.tickets_resolved) : []),
    [data],
  );

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
      <Group justify="space-between" mb="sm" align="flex-start" wrap="wrap" gap="sm">
        <div>
          <Title order={4}>Тренды по тикетам</Title>
          <Text size="sm" c="dimmed">
            Создание и решение запросов в динамике.
          </Text>
        </div>

        <Stack gap={4} align="flex-end">
          <Group gap={4} align="center">
            <ActionIcon
              variant="subtle"
              color="gray"
              size="sm"
              onClick={prevMonth}
              disabled={isMinMonth}
              aria-label="Предыдущий месяц"
            >
              <IconChevronLeft size={14} stroke={1.5} />
            </ActionIcon>
            <Text fw={600} w={130} ta="center">
              {formatMonthTitle(year, month)}
            </Text>
            <ActionIcon
              variant="subtle"
              color="gray"
              size="sm"
              onClick={nextMonth}
              disabled={isCurrentMonth}
              aria-label="Следующий месяц"
            >
              <IconChevronRight size={14} stroke={1.5} />
            </ActionIcon>
          </Group>
          <Text size="xs" c="dimmed">
            {formatMonthRange(year, month)}
          </Text>
        </Stack>
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
