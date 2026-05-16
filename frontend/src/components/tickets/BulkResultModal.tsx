import { Badge, Group, List, Modal, Stack, Text } from "@mantine/core";

import type { TicketBulkRejection, TicketBulkRejectionCode } from "../../api/types";

function getRejectionLabel(code: TicketBulkRejectionCode | string): string {
  switch (code) {
    case "has_reopens":
      return "Повторно открыт";
    case "has_unread_user_msg":
      return "Непрочитанное сообщение";
    case "wrong_status":
      return "Недопустимый статус";
    case "not_found":
      return "Не найден";
    case "invalid_transition":
      return "Недопустимый переход";
    default:
      return String(code);
  }
}

interface BulkResultModalProps {
  opened: boolean;
  onClose: () => void;
  applied: number;
  requested: number;
  rejected: TicketBulkRejection[];
}

export function BulkResultModal({
  opened,
  onClose,
  applied,
  requested,
  rejected,
}: BulkResultModalProps) {
  const allApplied = applied === requested;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Результат массового обновления"
      size="md"
    >
      <Stack gap="md">
        <Group gap="sm" align="center">
          <Badge
            color={allApplied ? "green" : "orange"}
            size="lg"
            variant="filled"
          >
            {applied} / {requested}
          </Badge>
          <Text size="sm">
            {allApplied
              ? "Все тикеты успешно обновлены"
              : `тикетов обновлено, ${rejected.length} пропущено`}
          </Text>
        </Group>

        {rejected.length > 0 && (
          <Stack gap="xs">
            <Text size="sm" fw={600} c="dimmed">
              Пропущенные тикеты
            </Text>
            <List spacing={6} size="sm" listStyleType="none">
              {rejected.map((item) => (
                <List.Item key={item.ticket_id}>
                  <Group gap="xs" wrap="nowrap">
                    <Text size="sm" c="dimmed" style={{ flexShrink: 0 }}>
                      #{item.ticket_id}
                    </Text>
                    <Badge size="xs" color="orange" variant="light">
                      {getRejectionLabel(item.code)}
                    </Badge>
                    {item.reason && (
                      <Text size="xs" c="dimmed" lineClamp={1}>
                        {item.reason}
                      </Text>
                    )}
                  </Group>
                </List.Item>
              ))}
            </List>
          </Stack>
        )}
      </Stack>
    </Modal>
  );
}
