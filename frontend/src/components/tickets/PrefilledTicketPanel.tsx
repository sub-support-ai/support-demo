import {
  Alert,
  Badge,
  Button,
  Group,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { IconCheck, IconEdit, IconTicket } from "@tabler/icons-react";
import { useEffect, useState } from "react";

import type { Ticket, TicketDraftUpdate } from "../../api/types";
import {
  getStatusLabel,
  getTicketPriorityLabel,
} from "../../lib/ticketLabels";

const DEPARTMENT_OPTIONS = [
  { value: "IT", label: "IT" },
  { value: "HR", label: "HR" },
  { value: "finance", label: "Финансы" },
];

const PRIORITY_OPTIONS = [
  { value: "низкий", label: "Низкий" },
  { value: "средний", label: "Средний" },
  { value: "высокий", label: "Высокий" },
  { value: "критический", label: "Критический" },
];

function normalizePriority(value?: string | null) {
  const normalized = value?.toLowerCase();
  return PRIORITY_OPTIONS.some((option) => option.value === normalized)
    ? normalized
    : "средний";
}

export function PrefilledTicketPanel({
  ticket,
  confirmLoading,
  saveLoading,
  onConfirm,
  onSave,
}: {
  ticket: Ticket;
  confirmLoading?: boolean;
  saveLoading?: boolean;
  onConfirm: () => void;
  onSave: (payload: TicketDraftUpdate) => Promise<void> | void;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [title, setTitle] = useState(ticket.title);
  const [body, setBody] = useState(ticket.body);
  const [department, setDepartment] = useState(ticket.department);
  const [priority, setPriority] = useState(normalizePriority(ticket.ai_priority));
  const [stepsTried, setStepsTried] = useState(ticket.steps_tried ?? "");

  const canEdit = !ticket.confirmed_by_user && ticket.status === "pending_user";
  const canSubmit = title.trim().length > 0 && body.trim().length > 0;

  useEffect(() => {
    setTitle(ticket.title);
    setBody(ticket.body);
    setDepartment(ticket.department);
    setPriority(normalizePriority(ticket.ai_priority));
    setStepsTried(ticket.steps_tried ?? "");
    setIsEditing(false);
  }, [ticket.id, ticket.title, ticket.body, ticket.department, ticket.ai_priority, ticket.steps_tried]);

  async function handleSave() {
    await onSave({
      title: title.trim(),
      body: body.trim(),
      department: department as "IT" | "HR" | "finance",
      ai_priority: priority as "низкий" | "средний" | "высокий" | "критический",
      steps_tried: stepsTried.trim() || null,
    });
    setIsEditing(false);
  }

  return (
    <Alert color="teal" variant="light" icon={<IconTicket size={18} />}>
      <Stack gap="sm">
        <Group justify="space-between" align="start">
          <div>
            <Title order={4}>Черновик тикета</Title>
            <Text size="sm" c="dimmed">
              Проверьте, что агент увидит правильное описание проблемы.
            </Text>
          </div>
          <Badge>{department}</Badge>
        </Group>

        <Group gap="xs">
          <Badge variant="light">{getStatusLabel(ticket.status)}</Badge>
          <Badge variant="light">{getTicketPriorityLabel(ticket)}</Badge>
        </Group>

        {isEditing ? (
          <Stack gap="sm">
            <TextInput
              label="Тема"
              value={title}
              maxLength={255}
              required
              onChange={(event) => setTitle(event.currentTarget.value)}
            />
            <Textarea
              label="Описание для агента"
              value={body}
              autosize
              minRows={5}
              maxRows={10}
              required
              onChange={(event) => setBody(event.currentTarget.value)}
            />
            <Group grow align="start">
              <Select
                label="Отдел поддержки"
                data={DEPARTMENT_OPTIONS}
                value={department}
                allowDeselect={false}
                onChange={(value) => value && setDepartment(value)}
              />
              <Select
                label="Приоритет"
                data={PRIORITY_OPTIONS}
                value={priority}
                allowDeselect={false}
                onChange={(value) => value && setPriority(value)}
              />
            </Group>
            <Textarea
              label="Что уже пробовали"
              value={stepsTried}
              autosize
              minRows={2}
              maxRows={5}
              placeholder="Например: перезагружал ноутбук, проверял кабель, пробовал другой браузер"
              onChange={(event) => setStepsTried(event.currentTarget.value)}
            />
            <Group gap="xs">
              <Button
                color="teal"
                loading={saveLoading}
                disabled={!canSubmit}
                onClick={handleSave}
              >
                Сохранить изменения
              </Button>
              <Button
                variant="subtle"
                color="gray"
                disabled={saveLoading}
                onClick={() => setIsEditing(false)}
              >
                Отмена
              </Button>
            </Group>
          </Stack>
        ) : (
          <Stack gap="sm">
            <div>
              <Text size="xs" c="dimmed" fw={600}>
                Тема
              </Text>
              <Text size="sm">{ticket.title}</Text>
            </div>
            <div>
              <Text size="xs" c="dimmed" fw={600}>
                Описание для агента
              </Text>
              <Text size="sm" className="draft-ticket-body">
                {ticket.body}
              </Text>
            </div>
            {ticket.steps_tried && (
              <div>
                <Text size="xs" c="dimmed" fw={600}>
                  Что уже пробовали
                </Text>
                <Text size="sm">{ticket.steps_tried}</Text>
              </div>
            )}
          </Stack>
        )}

        <Group gap="xs">
          <Button
            color="teal"
            leftSection={<IconCheck size={16} />}
            loading={confirmLoading}
            onClick={onConfirm}
            disabled={!canEdit || isEditing}
          >
            Отправить как есть
          </Button>
          <Button
            variant="light"
            leftSection={<IconEdit size={16} />}
            disabled={!canEdit || confirmLoading || saveLoading}
            onClick={() => setIsEditing(true)}
          >
            Изменить
          </Button>
        </Group>
      </Stack>
    </Alert>
  );
}
