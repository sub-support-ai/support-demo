import { Button, Group, Paper, Text } from "@mantine/core";
import { useState } from "react";

import { useSubmitKnowledgeFeedback } from "../../api/knowledge";
import type {
  EscalationContext,
  Message,
  RequestContextDefaults,
} from "../../api/types";
import { EscalationCard } from "./EscalationCard";
import { Sources } from "./Sources";

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
  onEscalate,
}: {
  message: Message;
  escalationDisabled?: boolean;
  escalationLoading?: boolean;
  contextDefaults?: RequestContextDefaults | null;
  onEscalate: (conversationId: number, context: EscalationContext) => void;
}) {
  const isUser = message.role === "user";

  if (!isUser && message.requires_escalation) {
    return (
      <div className="message-row ai">
        <div className="escalation-stack">
          {message.content && (
            <Paper className="message-bubble ai" withBorder>
              <Group gap="xs" mb={4}>
                <Text size="xs" fw={600} c="dimmed">
                  AI
                </Text>
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
        <Group gap="xs" mb={4}>
          <Text size="xs" fw={600} c="dimmed">
            {isUser ? "Вы" : "AI"}
          </Text>
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
