import { ActionIcon, Badge, Group, Paper, Text, Tooltip } from "@mantine/core";
import {
  IconThumbDown,
  IconThumbUp,
  IconX,
} from "@tabler/icons-react";
import { useState } from "react";

import { useSubmitKnowledgeFeedback } from "../../api/knowledge";
import type {
  EscalationContext,
  IntakeState,
  Message,
  RequestContextDefaults,
} from "../../api/types";
import { EscalationCard } from "./EscalationCard";
import { Sources } from "./Sources";

/** Визуальный индикатор уверенности модели.
 *  ≥ 0.8 — зелёный «уверен» (типично для KB-hit'ов с decision=answer)
 *  ≥ 0.6 — жёлтый «средне» (clarify или LLM с осторожным ответом)
 *  <  0.6 — красный «не уверен» (escalate / red zone)
 *  null  — не показываем (intake-сообщения, fallback'и без conf'а)
 */
function ConfidenceBadge({ confidence }: { confidence?: number | null }) {
  if (typeof confidence !== "number" || confidence <= 0) return null;
  let color: string;
  let label: string;
  let tooltip: string;
  if (confidence >= 0.8) {
    color = "green";
    label = "уверен";
    tooltip = "Ответ найден с высокой уверенностью";
  } else if (confidence >= 0.6) {
    color = "yellow";
    label = "средне";
    tooltip = "Ответ требует осторожной проверки";
  } else {
    color = "red";
    label = "не уверен";
    tooltip = "Лучше передать вопрос специалисту";
  }
  return (
    <Tooltip label={tooltip} withArrow>
      <Badge size="xs" variant="light" color={color}>
        {label}
      </Badge>
    </Tooltip>
  );
}

function KnowledgeFeedbackActions({ message }: { message: Message }) {
  const submitFeedback = useSubmitKnowledgeFeedback();
  const [selected, setSelected] = useState<string | null>(null);
  const source = message.sources?.find((item) => item.article_id);

  if (!source?.article_id) {
    return null;
  }

  async function handleFeedback(feedback: "helped" | "not_helped" | "not_relevant") {
    if (!source?.article_id) {
      return;
    }
    setSelected(feedback);
    try {
      await submitFeedback.mutateAsync({
        message_id: message.id,
        article_id: source.article_id,
        feedback,
      });
    } catch {
      setSelected(null);
    }
  }

  // После выбора фидбека показываем только результат, без других кнопок.
  if (selected) {
    return (
      <Group gap={6} mt="xs" align="center">
        <Text size="xs" c="dimmed">
          Спасибо за оценку
        </Text>
      </Group>
    );
  }

  return (
    <Group gap={4} mt="xs" align="center">
      <Text size="xs" c="dimmed" mr={4}>
        Помог ответ?
      </Text>
      <Tooltip label="Помогло" withArrow>
        <ActionIcon
          variant="subtle"
          color="teal"
          size="sm"
          loading={submitFeedback.isPending && selected === "helped"}
          onClick={() => handleFeedback("helped")}
          aria-label="Помогло"
        >
          <IconThumbUp size={16} stroke={1.5} />
        </ActionIcon>
      </Tooltip>
      <Tooltip label="Не помогло" withArrow>
        <ActionIcon
          variant="subtle"
          color="gray"
          size="sm"
          loading={submitFeedback.isPending && selected === "not_helped"}
          onClick={() => handleFeedback("not_helped")}
          aria-label="Не помогло"
        >
          <IconThumbDown size={16} stroke={1.5} />
        </ActionIcon>
      </Tooltip>
      <Tooltip label="Не относится к моему вопросу" withArrow>
        <ActionIcon
          variant="subtle"
          color="gray"
          size="sm"
          loading={submitFeedback.isPending && selected === "not_relevant"}
          onClick={() => handleFeedback("not_relevant")}
          aria-label="Не подходит"
        >
          <IconX size={16} stroke={1.5} />
        </ActionIcon>
      </Tooltip>
    </Group>
  );
}

export function MessageBubble({
  message,
  escalationDisabled,
  escalationLoading,
  contextDefaults,
  intakeState,
  showAiConfidence = false,
  showEscalationCard = true,
  onEscalate,
}: {
  message: Message;
  escalationDisabled?: boolean;
  escalationLoading?: boolean;
  contextDefaults?: RequestContextDefaults | null;
  intakeState?: IntakeState | null;
  showAiConfidence?: boolean;
  showEscalationCard?: boolean;
  onEscalate: (conversationId: number, context: EscalationContext) => void;
}) {
  const isUser = message.role === "user";

  if (!isUser && message.requires_escalation) {
    return (
      <div className="message-row ai">
        <div className="escalation-stack">
          {message.content && (
            <Paper className="message-bubble ai" withBorder>
              <Group gap="xs" mb={4} align="center">
                <Text size="xs" fw={600} c="dimmed">
                  AI
                </Text>
                {showAiConfidence && (
                  <ConfidenceBadge confidence={message.ai_confidence} />
                )}
              </Group>
              <Text size="sm" className="message-text">
                {message.content}
              </Text>
              <Sources sources={message.sources} />
              <KnowledgeFeedbackActions message={message} />
            </Paper>
          )}
          {showEscalationCard && (
            <EscalationCard
              contextDefaults={contextDefaults}
              intakeState={intakeState}
              disabled={escalationDisabled}
              loading={escalationLoading}
              onEscalate={(context) =>
                onEscalate(message.conversation_id, context)
              }
            />
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={`message-row ${isUser ? "user" : "ai"}`}>
      <Paper className={`message-bubble ${isUser ? "user" : "ai"}`} withBorder>
        <Group gap="xs" mb={4} align="center">
          <Text size="xs" fw={600} c="dimmed">
            {isUser ? "Вы" : "AI"}
          </Text>
          {!isUser && showAiConfidence && (
            <ConfidenceBadge confidence={message.ai_confidence} />
          )}
        </Group>
        <Text size="sm" className="message-text">
          {message.content}
        </Text>
        {!isUser && <Sources sources={message.sources} />}
        {!isUser && <KnowledgeFeedbackActions message={message} />}
      </Paper>
    </div>
  );
}
