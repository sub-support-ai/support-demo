import { Alert, Badge, Button, Group, Stack, Text, Title } from "@mantine/core";
import { IconCheck, IconTicket } from "@tabler/icons-react";

import type { Ticket } from "../../api/types";

export function PrefilledTicketPanel({
  ticket,
  confirmLoading,
  onConfirm,
}: {
  ticket: Ticket;
  confirmLoading?: boolean;
  onConfirm: () => void;
}) {
  return (
    <Alert color="teal" variant="light" icon={<IconTicket size={18} />}>
      <Stack gap="sm">
        <Group justify="space-between" align="start">
          <div>
            <Title order={4}>Готов черновик тикета</Title>
            <Text size="sm" c="dimmed">
              #{ticket.id}
            </Text>
          </div>
          <Badge>{ticket.department}</Badge>
        </Group>
        <div>
          <Text size="xs" c="dimmed" fw={600}>
            Тема
          </Text>
          <Text size="sm">{ticket.title}</Text>
        </div>
        <Group gap="xs">
          <Badge variant="light">Статус: {ticket.status}</Badge>
          {ticket.ai_priority && <Badge variant="light">{ticket.ai_priority}</Badge>}
        </Group>
        {ticket.steps_tried && (
          <div>
            <Text size="xs" c="dimmed" fw={600}>
              Что уже пробовали
            </Text>
            <Text size="sm">{ticket.steps_tried}</Text>
          </div>
        )}
        <Button
          color="teal"
          leftSection={<IconCheck size={16} />}
          loading={confirmLoading}
          onClick={onConfirm}
          disabled={ticket.confirmed_by_user || ticket.status !== "pending_user"}
        >
          Отправить в отдел
        </Button>
      </Stack>
    </Alert>
  );
}
