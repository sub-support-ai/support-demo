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
import { IconCheck, IconEdit, IconFileText } from "@tabler/icons-react";
import { useEffect, useState } from "react";

import type { Ticket, TicketDraftUpdate } from "../../api/types";
import {
  getDepartmentLabel,
  getStatusLabel,
  getTicketPriorityLabel,
} from "../../lib/ticketLabels";
import { validateEmail } from "../../lib/validation";

const DEPARTMENT_OPTIONS = [
  { value: "IT", label: "ИТ" },
  { value: "HR", label: "Кадры" },
  { value: "finance", label: "Финансы" },
  { value: "procurement", label: "Закупки" },
  { value: "security", label: "Безопасность" },
  { value: "facilities", label: "АХО" },
  { value: "documents", label: "Документооборот" },
];

const PRIORITY_OPTIONS = [
  { value: "низкий", label: "Низкий" },
  { value: "средний", label: "Средний" },
  { value: "высокий", label: "Высокий" },
];

const CRITICAL_PRIORITY_OPTION = {
  value: "критический",
  label: "Критический (системно)",
  disabled: true,
};

function normalizePriority(value?: string | null) {
  const normalized = value?.toLowerCase();
  if (normalized === CRITICAL_PRIORITY_OPTION.value) {
    return CRITICAL_PRIORITY_OPTION.value;
  }
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
  onSave: (payload: TicketDraftUpdate) => Promise<void>;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [title, setTitle] = useState(ticket.title);
  const [body, setBody] = useState(ticket.body);
  const [department, setDepartment] = useState(ticket.department);
  const [priority, setPriority] = useState(normalizePriority(ticket.ai_priority));
  const [requesterName, setRequesterName] = useState(ticket.requester_name ?? "");
  const [requesterEmail, setRequesterEmail] = useState(ticket.requester_email ?? "");
  const [office, setOffice] = useState(ticket.office ?? "");
  const [affectedItem, setAffectedItem] = useState(ticket.affected_item ?? "");
  const [requestType, setRequestType] = useState(ticket.request_type ?? "");
  const [requestDetails, setRequestDetails] = useState(ticket.request_details ?? "");
  const [stepsTried, setStepsTried] = useState(ticket.steps_tried ?? "");

  const canEdit = !ticket.confirmed_by_user && ticket.status === "pending_user";
  const requesterEmailError = validateEmail(requesterEmail);
  const hasRequiredContext =
    requesterName.trim().length > 0 &&
    !requesterEmailError &&
    office.trim().length > 0 &&
    affectedItem.trim().length > 0;
  const canSubmit =
    title.trim().length > 0 &&
    body.trim().length > 0 &&
    hasRequiredContext;
  const isCriticalPriority = priority === CRITICAL_PRIORITY_OPTION.value;

  useEffect(() => {
    setTitle(ticket.title);
    setBody(ticket.body);
    setDepartment(ticket.department);
    setPriority(normalizePriority(ticket.ai_priority));
    setRequesterName(ticket.requester_name ?? "");
    setRequesterEmail(ticket.requester_email ?? "");
    setOffice(ticket.office ?? "");
    setAffectedItem(ticket.affected_item ?? "");
    setRequestType(ticket.request_type ?? "");
    setRequestDetails(ticket.request_details ?? "");
    setStepsTried(ticket.steps_tried ?? "");
    setIsEditing(false);
  }, [
    ticket.id,
    ticket.title,
    ticket.body,
    ticket.department,
    ticket.ai_priority,
    ticket.requester_name,
    ticket.requester_email,
    ticket.office,
    ticket.affected_item,
    ticket.request_type,
    ticket.request_details,
    ticket.steps_tried,
  ]);

  async function handleSave() {
    const payload: TicketDraftUpdate = {
      title: title.trim(),
      body: body.trim(),
      department: department as TicketDraftUpdate["department"],
      requester_name: requesterName.trim(),
      requester_email: requesterEmail.trim(),
      office: office.trim() || null,
      affected_item: affectedItem.trim() || null,
      request_type: requestType.trim() || null,
      request_details: requestDetails.trim() || null,
      steps_tried: stepsTried.trim() || null,
    };
    if (!isCriticalPriority) {
      payload.ai_priority = priority as "низкий" | "средний" | "высокий";
    }
    await onSave(payload);
    setIsEditing(false);
  }

  return (
    <Alert color="teal" variant="light" icon={<IconFileText size={18} />}>
      <Stack gap="sm">
        <Group justify="space-between" align="start">
          <div>
            <Title order={4}>Черновик запроса</Title>
            <Text size="sm" c="dimmed">
              Проверьте, что агент увидит правильное описание проблемы.
            </Text>
          </div>
          <Badge>{getDepartmentLabel(department)}</Badge>
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
              <TextInput
                label="Заявитель"
                value={requesterName}
                maxLength={100}
                required
                onChange={(event) => setRequesterName(event.currentTarget.value)}
              />
              <TextInput
                label="Email заявителя"
                value={requesterEmail}
                maxLength={255}
                required
                error={requesterEmail ? requesterEmailError : undefined}
                onChange={(event) => setRequesterEmail(event.currentTarget.value)}
              />
            </Group>
            <Group grow align="start">
              <Select
                label="Отдел поддержки"
                data={DEPARTMENT_OPTIONS}
                value={department}
                allowDeselect={false}
                onChange={(value) => value && setDepartment(value)}
              />
              {isCriticalPriority ? (
                <TextInput
                  label="Приоритет"
                  value={CRITICAL_PRIORITY_OPTION.label}
                  disabled
                />
              ) : (
                <Select
                  label="Приоритет"
                  data={PRIORITY_OPTIONS}
                  value={priority}
                  allowDeselect={false}
                  onChange={(value) => value && setPriority(value)}
                />
              )}
            </Group>
            <Group grow align="start">
              <TextInput
                label="Офис"
                value={office}
                maxLength={100}
                required
                onChange={(event) => setOffice(event.currentTarget.value)}
              />
              <TextInput
                label="Что затронуто"
                value={affectedItem}
                maxLength={150}
                required
                onChange={(event) => setAffectedItem(event.currentTarget.value)}
              />
            </Group>
            <Group grow align="start">
              <TextInput
                label="Тип запроса"
                value={requestType}
                maxLength={60}
                onChange={(event) => setRequestType(event.currentTarget.value)}
              />
              <TextInput
                label="Уточнение формы"
                value={requestDetails}
                maxLength={2000}
                onChange={(event) => setRequestDetails(event.currentTarget.value)}
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
            {!hasRequiredContext && canEdit && (
              <Alert color="yellow" variant="light">
                Заполните заявителя, корректный email, офис и затронутый объект перед отправкой.
              </Alert>
            )}
            <div>
              <Text size="xs" c="dimmed" fw={600}>
                Тема
              </Text>
              <Text size="sm">{ticket.title}</Text>
            </div>
            <div>
              <Text size="xs" c="dimmed" fw={600}>
                Контекст
              </Text>
              <Text size="sm">
                {ticket.requester_name || ticket.requester_email || "Автор не указан"}
                {ticket.office ? ` · ${ticket.office}` : ""}
                {ticket.affected_item ? ` · ${ticket.affected_item}` : ""}
              </Text>
            </div>
            {(ticket.request_type || ticket.request_details) && (
              <div>
                <Text size="xs" c="dimmed" fw={600}>
                  Форма запроса
                </Text>
                <Text size="sm">
                  {[ticket.request_type, ticket.request_details]
                    .filter(Boolean)
                    .join(" · ")}
                </Text>
              </div>
            )}
            <div>
              <Text size="xs" c="dimmed" fw={600}>
                Описание для агента
              </Text>
              <Text size="sm" className="draft-ticket-body">
                {ticket.body}
              </Text>
            </div>
            {(ticket.request_type || ticket.request_details) && (
              <div>
                <Text size="xs" c="dimmed" fw={600}>
                  Форма запроса
                </Text>
                <Text size="sm">
                  {[ticket.request_type, ticket.request_details]
                    .filter(Boolean)
                    .join(" · ")}
                </Text>
              </div>
            )}
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

        {canEdit && (
          <Group gap="xs">
            <Button
              color="teal"
              leftSection={<IconCheck size={16} />}
              loading={confirmLoading}
              onClick={onConfirm}
              disabled={isEditing || !hasRequiredContext}
            >
              Отправить как есть
            </Button>
            <Button
              variant="light"
              leftSection={<IconEdit size={16} />}
              disabled={confirmLoading || saveLoading}
              onClick={() => setIsEditing(true)}
            >
              Изменить
            </Button>
          </Group>
        )}
      </Stack>
    </Alert>
  );
}
