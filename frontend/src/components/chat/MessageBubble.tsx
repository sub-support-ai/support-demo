import { Group, Paper, Text } from "@mantine/core";

import type {
  EscalationContext,
  Message,
  RequestContextDefaults,
} from "../../api/types";
import { EscalationCard } from "./EscalationCard";
import { Sources } from "./Sources";

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
      </Paper>
    </div>
  );
}
