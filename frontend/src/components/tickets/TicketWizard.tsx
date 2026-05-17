import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  Progress,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import {
  IconArrowLeft,
  IconArrowRight,
  IconCheck,
  IconSparkles,
} from "@tabler/icons-react";
import { useEffect, useMemo, useState } from "react";

import { useEscalateConversation, useSendMessage } from "../../api/conversations";
import type { Conversation, EscalationContext, Ticket, UserMe } from "../../api/types";

const FIELD_LABELS: Record<FieldKey, string> = {
  office: "В каком офисе возникла проблема?",
  affected_item: "Что именно затронуто?",
};

const FIELD_SHORT_LABELS: Record<FieldKey, string> = {
  office: "Офис",
  affected_item: "Что затронуто",
};

const FIELD_PLACEHOLDERS: Record<FieldKey, string> = {
  office: "Москва, БЦ Северная башня, кабинет 301",
  affected_item: "Ноутбук Dell, VPN-клиент, принтер на 3 этаже",
};

const REQUIRED_FIELDS = ["office", "affected_item"] as const;
type FieldKey = (typeof REQUIRED_FIELDS)[number];

type Stage = "describe" | "ai-processing" | "field" | "review";

function isFieldKey(value: string): value is FieldKey {
  return (REQUIRED_FIELDS as readonly string[]).includes(value);
}

function getFieldError(_field: FieldKey, value: string): string | null {
  if (!value.trim()) return "Заполните поле";
  return null;
}

export function TicketWizard({
  conversation,
  isAiProcessing,
  me,
  onCancel,
  onTicketCreated,
}: {
  conversation: Conversation;
  isAiProcessing: boolean;
  me?: UserMe | null;
  onCancel: () => void;
  onTicketCreated: (ticket: Ticket) => void;
}) {
  const sendMessage = useSendMessage();
  const escalate = useEscalateConversation();

  const [description, setDescription] = useState("");
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({});
  const [stage, setStage] = useState<Stage>("describe");
  const [currentField, setCurrentField] = useState<FieldKey | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [aiConsumed, setAiConsumed] = useState(false);

  useEffect(() => {
    if (stage !== "ai-processing") return;
    if (isAiProcessing) return;
    if (aiConsumed) return;

    const collected = conversation.intake_state?.fields ?? {};
    const prefilled: Record<string, string> = {};
    for (const field of REQUIRED_FIELDS) {
      const raw = collected[field];
      if (typeof raw === "string" && raw.trim()) {
        prefilled[field] = raw.trim();
      }
    }
    setFieldValues(prefilled);
    setAiConsumed(true);

    const firstMissing = REQUIRED_FIELDS.find((field) => !prefilled[field]);
    if (firstMissing) {
      setCurrentField(firstMissing);
      setStage("field");
    } else {
      setCurrentField(null);
      setStage("review");
    }
  }, [stage, isAiProcessing, aiConsumed, conversation.intake_state]);

  const missingFieldsList = useMemo(
    () => REQUIRED_FIELDS.filter((field) => !(fieldValues[field] ?? "").trim()),
    [fieldValues],
  );

  async function handleDescribeSubmit() {
    const text = description.trim();
    if (!text) return;
    setError(null);
    try {
      await sendMessage.mutateAsync({ conversationId: conversation.id, content: text });
      setAiConsumed(false);
      setStage("ai-processing");
    } catch {
      setError("Не удалось отправить описание. Попробуйте ещё раз.");
    }
  }

  function handleFieldSubmit() {
    if (!currentField) return;
    const value = (fieldValues[currentField] ?? "").trim();
    if (getFieldError(currentField, value)) return;

    const nextMissing = REQUIRED_FIELDS.find(
      (field) => field !== currentField && !(fieldValues[field] ?? "").trim(),
    );
    if (nextMissing) {
      setCurrentField(nextMissing);
    } else {
      setCurrentField(null);
      setStage("review");
    }
  }

  async function handleFinalSubmit() {
    setError(null);
    const context: EscalationContext = {
      requester_name: me?.request_context?.requester_name || me?.username || null,
      requester_email: me?.request_context?.requester_email || me?.email || null,
      office: fieldValues.office?.trim() || null,
      affected_item: fieldValues.affected_item?.trim() || null,
    };
    try {
      const response = await escalate.mutateAsync({
        conversationId: conversation.id,
        context,
      });
      onTicketCreated(response.ticket);
    } catch {
      setError("Не удалось создать черновик. Проверьте данные и попробуйте ещё раз.");
    }
  }

  const totalSteps = 2 + REQUIRED_FIELDS.length;
  const filledRequiredCount = REQUIRED_FIELDS.filter(
    (field) => (fieldValues[field] ?? "").trim().length > 0,
  ).length;
  const stepNumber =
    stage === "describe"
      ? 1
      : stage === "ai-processing"
        ? 2
        : stage === "field"
          ? 2 + filledRequiredCount + 1
          : totalSteps;
  const progressValue = Math.min(100, (stepNumber / totalSteps) * 100);

  return (
    <Paper className="wizard-shell" withBorder radius="md">
      <Stack className="wizard-frame" gap="md">
        <Group justify="space-between" align="center">
          <Badge variant="light" color="teal" size="sm">
            Шаг {Math.min(stepNumber, totalSteps)} из {totalSteps}
          </Badge>
          <Button variant="subtle" color="gray" size="xs" onClick={onCancel}>
            Отмена
          </Button>
        </Group>
        <Progress value={progressValue} size="xs" color="teal" />

        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}

        {stage === "describe" && (
          <DescribeStep
            value={description}
            onChange={setDescription}
            onSubmit={handleDescribeSubmit}
            loading={sendMessage.isPending}
          />
        )}

        {stage === "ai-processing" && <ProcessingStep />}

        {stage === "field" && currentField && (
          <FieldStep
            key={currentField}
            field={currentField}
            value={fieldValues[currentField] ?? ""}
            onChange={(value) =>
              setFieldValues((prev) => ({ ...prev, [currentField]: value }))
            }
            onSubmit={handleFieldSubmit}
            onBack={() => setStage("describe")}
            filledCount={filledRequiredCount}
            totalRequired={REQUIRED_FIELDS.length}
          />
        )}

        {stage === "review" && (
          <ReviewStep
            description={description}
            onDescriptionChange={setDescription}
            fieldValues={fieldValues}
            onFieldChange={(field, value) =>
              setFieldValues((prev) => ({ ...prev, [field]: value }))
            }
            onBack={() => {
              const firstMissing = REQUIRED_FIELDS.find(
                (field) => !(fieldValues[field] ?? "").trim(),
              );
              if (firstMissing) {
                setCurrentField(firstMissing);
                setStage("field");
              } else {
                setStage("describe");
              }
            }}
            onSubmit={handleFinalSubmit}
            submitting={escalate.isPending}
            canSubmit={
              description.trim().length > 0 &&
              missingFieldsList.length === 0
            }
          />
        )}
      </Stack>
    </Paper>
  );
}

function DescribeStep({
  value,
  onChange,
  onSubmit,
  loading,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  loading: boolean;
}) {
  return (
    <Stack gap="md" className="wizard-step">
      <Title order={2} className="wizard-question">
        Что случилось?
      </Title>
      <Text size="sm" c="dimmed">
        Опишите проблему своими словами. Чем подробнее описание, тем точнее
        система подготовит черновик для специалиста.
      </Text>
      <Textarea
        autoFocus
        value={value}
        onChange={(event) => onChange(event.currentTarget.value)}
        placeholder="Например: со вчерашнего дня не могу подключиться к VPN, ошибка Authentication failed..."
        autosize
        minRows={4}
        maxRows={10}
        classNames={{ input: "wizard-input wizard-input-large" }}
        onKeyDown={(event) => {
          if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            onSubmit();
          }
        }}
      />
      <Group justify="space-between" align="center">
        <Text size="xs" c="dimmed">
          Ctrl + Enter - далее
        </Text>
        <Button
          size="md"
          color="teal"
          rightSection={<IconArrowRight size={16} />}
          loading={loading}
          disabled={!value.trim()}
          onClick={onSubmit}
        >
          Далее
        </Button>
      </Group>
    </Stack>
  );
}

function ProcessingStep() {
  return (
    <Stack gap="md" align="center" className="wizard-step wizard-loading">
      <IconSparkles size={36} color="var(--mantine-color-teal-6)" />
      <Title order={3} className="wizard-question">
        Анализирую обращение
      </Title>
      <Text size="sm" c="dimmed" ta="center">
        Подбираю категорию и извлекаю детали из текста.
      </Text>
      <Loader color="teal" size="sm" />
    </Stack>
  );
}

function FieldStep({
  field,
  value,
  onChange,
  onSubmit,
  onBack,
  filledCount,
  totalRequired,
}: {
  field: FieldKey;
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onBack: () => void;
  filledCount: number;
  totalRequired: number;
}) {
  const error = value.trim().length > 0 ? getFieldError(field, value) : null;
  const disabled = getFieldError(field, value) !== null;

  return (
    <Stack gap="md" className="wizard-step">
      <Text size="xs" c="teal" fw={700} tt="uppercase">
        Уточнение {filledCount + 1} из {totalRequired}
      </Text>
      <Title order={2} className="wizard-question">
        {FIELD_LABELS[field]}
      </Title>
      <TextInput
        autoFocus
        value={value}
        onChange={(event) => onChange(event.currentTarget.value)}
        placeholder={FIELD_PLACEHOLDERS[field]}
        classNames={{ input: "wizard-input wizard-input-large" }}
        error={error ?? undefined}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            onSubmit();
          }
        }}
      />
      <Group justify="space-between" align="center">
        <Button
          variant="subtle"
          color="gray"
          size="sm"
          leftSection={<IconArrowLeft size={14} />}
          onClick={onBack}
        >
          Назад
        </Button>
        <Group gap="xs" align="center">
          <Text size="xs" c="dimmed">
            Enter - далее
          </Text>
          <Button
            size="md"
            color="teal"
            rightSection={<IconArrowRight size={16} />}
            disabled={disabled}
            onClick={onSubmit}
          >
            Далее
          </Button>
        </Group>
      </Group>
    </Stack>
  );
}

function ReviewStep({
  description,
  onDescriptionChange,
  fieldValues,
  onFieldChange,
  onBack,
  onSubmit,
  submitting,
  canSubmit,
}: {
  description: string;
  onDescriptionChange: (value: string) => void;
  fieldValues: Record<string, string>;
  onFieldChange: (field: FieldKey, value: string) => void;
  onBack: () => void;
  onSubmit: () => void;
  submitting: boolean;
  canSubmit: boolean;
}) {
  return (
    <Stack gap="md" className="wizard-step">
      <Title order={2} className="wizard-question">
        Проверьте черновик
      </Title>
      <Text size="sm" c="dimmed">
        Перед созданием черновика можно поправить описание и обязательные поля.
      </Text>
      <Stack gap="xs" className="wizard-review">
        <Textarea
          label="Описание"
          value={description}
          onChange={(event) => onDescriptionChange(event.currentTarget.value)}
          autosize
          minRows={2}
          maxRows={6}
        />
        {REQUIRED_FIELDS.map((field) => {
          const value = fieldValues[field] ?? "";
          const error =
            value.trim().length > 0 && isFieldKey(field)
              ? getFieldError(field, value)
              : null;
          return (
            <TextInput
              key={field}
              label={FIELD_SHORT_LABELS[field]}
              value={value}
              onChange={(event) => onFieldChange(field, event.currentTarget.value)}
              error={error ?? undefined}
            />
          );
        })}
      </Stack>
      <Group justify="space-between" align="center" mt="sm">
        <Button
          variant="subtle"
          color="gray"
          size="sm"
          leftSection={<IconArrowLeft size={14} />}
          onClick={onBack}
        >
          Назад
        </Button>
        <Button
          size="md"
          color="teal"
          leftSection={<IconCheck size={18} />}
          loading={submitting}
          disabled={!canSubmit}
          onClick={onSubmit}
        >
          Создать черновик
        </Button>
      </Group>
    </Stack>
  );
}
