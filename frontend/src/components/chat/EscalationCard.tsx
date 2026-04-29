import { Alert, Button, Group, Text } from "@mantine/core";
import { IconArrowRight, IconAlertTriangle } from "@tabler/icons-react";

export function EscalationCard({
  loading,
  onEscalate,
}: {
  loading?: boolean;
  onEscalate: () => void;
}) {
  return (
    <Alert
      color="red"
      variant="light"
      icon={<IconAlertTriangle size={18} />}
      className="escalation-card"
    >
      <Group justify="space-between" align="center" gap="md">
        <div>
          <Text fw={600}>Нужна проверка специалиста</Text>
          <Text size="sm" c="dimmed">
            Передам обращение в профильный отдел.
          </Text>
        </div>
        <Button
          color="red"
          rightSection={<IconArrowRight size={16} />}
          loading={loading}
          onClick={onEscalate}
        >
          Создать тикет
        </Button>
      </Group>
    </Alert>
  );
}
