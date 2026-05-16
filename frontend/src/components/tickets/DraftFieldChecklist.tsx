import { Button, Group, Progress, Stack, Text } from "@mantine/core";
import {
  IconAlertTriangle,
  IconCheck,
  IconX,
} from "@tabler/icons-react";

export type FieldStatus = "ok" | "warning" | "empty";

export interface DraftField {
  key: string;
  label: string;
  value: string;
  required: boolean;
  warning?: string | null;
}

export function getFieldStatus(field: DraftField): FieldStatus {
  if (!field.value.trim()) return "empty";
  if (field.warning) return "warning";
  return "ok";
}

/**
 * Чеклист полей черновика — отображает статус каждого поля (✅/⚠️/❌).
 * В режиме canEdit показывает кнопку «×» для очистки заполненных полей с предупреждением.
 */
export function DraftFieldChecklist({
  fields,
  onClear,
}: {
  fields: DraftField[];
  /** Если передан — показывает кнопку очистки на полях со статусом warning. */
  onClear?: (key: string) => void;
}) {
  const requiredFields = fields.filter((f) => f.required);
  const filled = requiredFields.filter((f) => getFieldStatus(f) === "ok").length;
  const total = requiredFields.length;

  return (
    <Stack gap="sm">
      {total > 0 && (
        <Group gap="xs" align="center">
          <Text size="xs" c="dimmed" fw={600}>
            Заполнено {filled} из {total}
          </Text>
          <Progress
            value={total > 0 ? (filled / total) * 100 : 0}
            size="xs"
            style={{ flex: 1 }}
            color={filled === total ? "teal" : "yellow"}
          />
        </Group>
      )}

      {fields.map((field) => {
        const status = getFieldStatus(field);
        return (
          <Group
            key={field.key}
            justify="space-between"
            gap="xs"
            wrap="nowrap"
            align="flex-start"
          >
            <Group gap={6} wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
              {status === "ok" && (
                <IconCheck
                  size={14}
                  color="var(--mantine-color-teal-6)"
                  style={{ flexShrink: 0, marginTop: 3 }}
                />
              )}
              {status === "warning" && (
                <IconAlertTriangle
                  size={14}
                  color="var(--mantine-color-orange-6)"
                  style={{ flexShrink: 0, marginTop: 3 }}
                />
              )}
              {status === "empty" && (
                <IconX
                  size={14}
                  color="var(--mantine-color-gray-5)"
                  style={{ flexShrink: 0, marginTop: 3 }}
                />
              )}
              <div style={{ minWidth: 0 }}>
                <Text size="xs" c="dimmed" fw={600}>
                  {field.label}
                  {field.required && (
                    <Text span c="red" ml={2}>
                      *
                    </Text>
                  )}
                </Text>
                {status === "empty" ? (
                  <Text size="sm" c="dimmed" fs="italic">
                    не заполнено
                  </Text>
                ) : (
                  <Text size="sm" lineClamp={2}>
                    {field.value}
                  </Text>
                )}
                {status === "warning" && field.warning && (
                  <Text size="xs" c="orange">
                    {field.warning}
                  </Text>
                )}
              </div>
            </Group>
            {status !== "empty" && onClear && (
              <Button
                variant="subtle"
                color="gray"
                size="compact-xs"
                px={4}
                title={`Очистить: ${field.label}`}
                onClick={() => onClear(field.key)}
              >
                ×
              </Button>
            )}
          </Group>
        );
      })}
    </Stack>
  );
}
