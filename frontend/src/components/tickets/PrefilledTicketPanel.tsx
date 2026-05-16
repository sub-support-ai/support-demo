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
import {
  IconAlertTriangle,
  IconCheck,
  IconEdit,
  IconFileText,
  IconX,
} from "@tabler/icons-react";
import { useEffect, useMemo, useState } from "react";

import type { IntakeState, Ticket, TicketDraftUpdate } from "../../api/types";
import {
  getDepartmentLabel,
  getStatusLabel,
  getTicketPriorityLabel,
} from "../../lib/ticketLabels";
import { validateEmail } from "../../lib/validation";
import { type DraftField, DraftFieldChecklist } from "./DraftFieldChecklist";

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

/**
 * Предупреждение для поля — возвращает строку если значение вызывает сомнение.
 * Вызывать только если поле не пустое.
 */
function getFieldWarning(field: string, value: string): string | null {
  if (!value.trim()) return null;
  if (field === "requester_email") return validateEmail(value) ?? null;
  return null;
}

/**
 * Вернуть значение поля из тикета если заполнено,
 * иначе — из intake_state.fields (фоллбэк пока тикет ещё не обновлён сервером).
 */
function intakeValue(
  field: string,
  ticketVal: string | null | undefined,
  intakeFields?: Record<string, string | null | undefined> | null,
): string {
  const v = (ticketVal ?? "").trim();
  if (v) return v;
  return ((intakeFields ?? {})[field] ?? "").trim();
}

export function PrefilledTicketPanel({
  ticket,
  intakeState,
  potentialDuplicates,
  confirmLoading,
  declineLoading,
  saveLoading,
  onConfirm,
  onDecline,
  onSave,
}: {
  ticket: Ticket;
  /** Состояние intake — для предзаполнения пустых полей и расширенной валидации. */
  intakeState?: IntakeState | null;
  /** Уже открытые тикеты пользователя, похожие на текущий черновик.
   *  Если массив непустой и тикет ещё редактируемый — покажем предупреждение
   *  с предложением проверить, не плодит ли пользователь дубликат. */
  potentialDuplicates?: Ticket[];
  confirmLoading?: boolean;
  declineLoading?: boolean;
  saveLoading?: boolean;
  onConfirm: () => void;
  onDecline: () => void;
  onSave: (payload: TicketDraftUpdate) => Promise<void>;
}) {
  const intakeFields = intakeState?.fields ?? null;

  const [isEditing, setIsEditing] = useState(false);
  const [title, setTitle] = useState(ticket.title);
  const [body, setBody] = useState(ticket.body);
  const [department, setDepartment] = useState(ticket.department);
  const [priority, setPriority] = useState(normalizePriority(ticket.ai_priority));
  const [requesterName, setRequesterName] = useState(
    intakeValue("requester_name", ticket.requester_name, intakeFields),
  );
  const [requesterEmail, setRequesterEmail] = useState(
    intakeValue("requester_email", ticket.requester_email, intakeFields),
  );
  const [office, setOffice] = useState(
    intakeValue("office", ticket.office, intakeFields),
  );
  const [affectedItem, setAffectedItem] = useState(
    intakeValue("affected_item", ticket.affected_item, intakeFields),
  );
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

  // Поля для чеклиста — пересчитываются при изменении любого значения.
  const contextFields: DraftField[] = useMemo(
    () => [
      {
        key: "requester_name",
        label: "Заявитель",
        value: requesterName,
        required: true,
        warning: getFieldWarning("requester_name", requesterName),
      },
      {
        key: "requester_email",
        label: "Email",
        value: requesterEmail,
        required: true,
        warning: getFieldWarning("requester_email", requesterEmail),
      },
      {
        key: "office",
        label: "Офис",
        value: office,
        required: true,
        warning: getFieldWarning("office", office),
      },
      {
        key: "affected_item",
        label: "Что затронуто",
        value: affectedItem,
        required: true,
        warning: getFieldWarning("affected_item", affectedItem),
      },
      ...(requestType
        ? [
            {
              key: "request_type",
              label: "Тип запроса",
              value: requestType,
              required: false,
              warning: null,
            },
          ]
        : []),
    ],
    [requesterName, requesterEmail, office, affectedItem, requestType],
  );

  function handleClearField(key: string) {
    switch (key) {
      case "requester_name":
        setRequesterName("");
        break;
      case "requester_email":
        setRequesterEmail("");
        break;
      case "office":
        setOffice("");
        break;
      case "affected_item":
        setAffectedItem("");
        break;
      case "request_type":
        setRequestType("");
        break;
    }
  }

  // При смене тикета или обновлении intake_state — пересинхронизировать локальный стейт.
  useEffect(() => {
    const fields = intakeState?.fields ?? null;
    setTitle(ticket.title);
    setBody(ticket.body);
    setDepartment(ticket.department);
    setPriority(normalizePriority(ticket.ai_priority));
    setRequesterName(intakeValue("requester_name", ticket.requester_name, fields));
    setRequesterEmail(intakeValue("requester_email", ticket.requester_email, fields));
    setOffice(intakeValue("office", ticket.office, fields));
    setAffectedItem(intakeValue("affected_item", ticket.affected_item, fields));
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
    intakeState?.fields,
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
          <Badge variant="light">Отдел: {getDepartmentLabel(ticket.department)}</Badge>
          <Badge variant="light">Приоритет: {getTicketPriorityLabel(ticket)}</Badge>
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
            {/* Чеклист контактных / контекстных полей */}
            <DraftFieldChecklist
              fields={contextFields}
              onClear={canEdit ? handleClearField : undefined}
            />

            <div>
              <Text size="xs" c="dimmed" fw={600}>
                Тема
              </Text>
              <Text size="sm">{title}</Text>
            </div>
            <div>
              <Text size="xs" c="dimmed" fw={600}>
                Описание для агента
              </Text>
              <Text size="sm" className="draft-ticket-body">
                {body}
              </Text>
            </div>
            {requestDetails && (
              <div>
                <Text size="xs" c="dimmed" fw={600}>
                  Форма запроса
                </Text>
                <Text size="sm">{requestDetails}</Text>
              </div>
            )}
            {stepsTried && (
              <div>
                <Text size="xs" c="dimmed" fw={600}>
                  Что уже пробовали
                </Text>
                <Text size="sm">{stepsTried}</Text>
              </div>
            )}
          </Stack>
        )}

        {/* Предупреждение о потенциальных дубликатах — только пока тикет
            ещё редактируемый. После подтверждения тикета смысла показывать нет. */}
        {canEdit && potentialDuplicates && potentialDuplicates.length > 0 && (
          <Alert
            color="yellow"
            variant="light"
            icon={<IconAlertTriangle size={16} />}
            title={
              potentialDuplicates.length === 1
                ? "Похожий запрос уже открыт"
                : `Похожих запросов открыто: ${potentialDuplicates.length}`
            }
          >
            <Stack gap={4}>
              {potentialDuplicates.slice(0, 3).map((dup) => (
                <Text key={dup.id} size="xs">
                  #{dup.id} «{dup.title}» — {getStatusLabel(dup.status)}
                </Text>
              ))}
              {potentialDuplicates.length > 3 && (
                <Text size="xs" c="dimmed">
                  и ещё {potentialDuplicates.length - 3}…
                </Text>
              )}
            </Stack>
            <Text size="xs" c="dimmed" mt={6}>
              Можно отменить черновик или всё равно отправить.
            </Text>
          </Alert>
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
              Отправить
            </Button>
            <Button
              variant="light"
              leftSection={<IconEdit size={16} />}
              disabled={confirmLoading || saveLoading}
              onClick={() => setIsEditing(true)}
            >
              Изменить
            </Button>
            <Button
              variant="subtle"
              color="red"
              leftSection={<IconX size={16} />}
              loading={declineLoading}
              disabled={confirmLoading || saveLoading || isEditing}
              onClick={onDecline}
            >
              Отменить
            </Button>
          </Group>
        )}
      </Stack>
    </Alert>
  );
}
