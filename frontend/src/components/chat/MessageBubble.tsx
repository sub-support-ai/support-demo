import { Group, Paper, Text } from "@mantine/core";

import type { Message } from "../../api/types";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { EscalationCard } from "./EscalationCard";
import { Sources } from "./Sources";

export function MessageBubble({
  message,
  escalationLoading,
  onEscalate,
}: {
  message: Message;
  escalationLoading?: boolean;
  onEscalate: () => void;
}) {
  const isUser = message.role === "user";

  if (!isUser && message.requires_escalation) {
    return (
      <div className="message-row ai">
        <EscalationCard loading={escalationLoading} onEscalate={onEscalate} />
      </div>
    );
  }

  return (
    <div className={`message-row ${isUser ? "user" : "ai"}`}>
      <Paper className={`message-bubble ${isUser ? "user" : "ai"}`} withBorder>
        <Group justify="space-between" gap="xs" mb={4}>
          <Text size="xs" fw={600} c="dimmed">
            {isUser ? "Вы" : "AI"}
          </Text>
          {!isUser && <ConfidenceBadge confidence={message.ai_confidence} />}
        </Group>
        <Text size="sm" className="message-text">
          {message.content}
        </Text>
        {!isUser && <Sources sources={message.sources} />}
      </Paper>
    </div>
  );
}
