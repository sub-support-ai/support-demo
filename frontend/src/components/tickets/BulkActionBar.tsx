import { ActionIcon, Badge, Button, Group, Paper, Text } from "@mantine/core";
import { IconX } from "@tabler/icons-react";

import type { TicketBulkAction } from "../../api/types";

function pluralizeTickets(count: number): string {
  if (count % 10 === 1 && count % 100 !== 11) return "тикет";
  if (
    count % 10 >= 2 &&
    count % 10 <= 4 &&
    (count % 100 < 10 || count % 100 >= 20)
  )
    return "тикета";
  return "тикетов";
}

interface BulkActionBarProps {
  selectedCount: number;
  isAdmin?: boolean;
  loading?: boolean;
  onAction: (action: TicketBulkAction, force?: boolean) => void;
  onClear: () => void;
}

export function BulkActionBar({
  selectedCount,
  isAdmin,
  loading,
  onAction,
  onClear,
}: BulkActionBarProps) {
  if (selectedCount === 0) return null;

  return (
    <Paper
      className="bulk-action-bar"
      withBorder
      shadow="md"
      style={{ position: "sticky", bottom: 16, zIndex: 100 }}
    >
      <Group justify="space-between" wrap="nowrap">
        <Group gap="sm" wrap="nowrap">
          <Badge size="lg" variant="filled" color="blue">
            {selectedCount}
          </Badge>
          <Text size="sm" fw={500}>
            {pluralizeTickets(selectedCount)} выбрано
          </Text>
        </Group>

        <Group gap="xs" wrap="nowrap">
          <Button
            size="xs"
            variant="light"
            loading={loading}
            onClick={() => onAction("in_progress")}
          >
            В работу
          </Button>
          <Button
            size="xs"
            variant="light"
            color="green"
            loading={loading}
            onClick={() => onAction("resolved")}
          >
            Решено
          </Button>
          <Button
            size="xs"
            variant="light"
            color="gray"
            loading={loading}
            onClick={() => onAction("closed")}
          >
            Закрыть
          </Button>
          {isAdmin && (
            <Button
              size="xs"
              variant="outline"
              color="red"
              loading={loading}
              title="Закрыть принудительно, обходя проверки (только admin)"
              onClick={() => onAction("closed", true)}
            >
              Закрыть force
            </Button>
          )}
          <ActionIcon
            variant="subtle"
            color="gray"
            size="sm"
            disabled={loading}
            title="Снять выделение"
            onClick={onClear}
          >
            <IconX size={14} />
          </ActionIcon>
        </Group>
      </Group>
    </Paper>
  );
}
