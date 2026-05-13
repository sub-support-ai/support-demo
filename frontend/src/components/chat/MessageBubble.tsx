import { Badge, Button, Group, Paper, Text, Tooltip } from "@mantine/core";
import { useState } from "react";

import { useSubmitKnowledgeFeedback } from "../../api/knowledge";
import type {
  EscalationContext,
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

  return (
    <Group gap="xs" mt="sm">
      <Button
        size="xs"
        variant={selected === "helped" ? "filled" : "light"}
        loading={submitFeedback.isPending && selected === "helped"}
        onClick={() => handleFeedback("helped")}
      >
        Помогло
      </Button>
      <Button
        size="xs"
        variant={selected === "not_helped" ? "filled" : "subtle"}
        loading={submitFeedback.isPending && selected === "not_helped"}
        onClick={() => handleFeedback("not_helped")}
      >
        Не помогло
      </Button>
      <Button
        size="xs"
        variant={selected === "not_relevant" ? "filled" : "subtle"}
        loading={submitFeedback.isPending && selected === "not_relevant"}
        onClick={() => handleFeedback("not_relevant")}
      >
        Не подходит
      </Button>
    </Group>
  );
}

export function MessageBubble({
  message,
  escalationDisabled,
  escalationLoading,
  contextDefaults,
  showAiConfidence = false,
  onEscalate,
}: {
  message: Message;
  escalationDisabled?: boolean;
  escalationLoading?: boolean;
  contextDefaults?: RequestContextDefaults | null;
  showAiConfidence?: boolean;
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
          <EscalationCard
            contextDefaults={contextDefaults}
            disabled={escalationDisabled}
            loading={escalationLoading}
            onEscalate={(context) =>
              onEscalate(message.conversation_id, context)
            }
          />
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
