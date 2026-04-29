import { Badge, Group, Paper, Stack, Text, Title } from "@mantine/core";

import type { Ticket } from "../../api/types";
import { ConfidenceBadge } from "../chat/ConfidenceBadge";

export function TicketCard({ ticket }: { ticket: Ticket }) {
  return (
    <Paper className="ticket-card" withBorder>
      <Stack gap="xs">
        <Group justify="space-between" align="start">
          <div>
            <Title order={4}>{ticket.title}</Title>
            <Text size="xs" c="dimmed">
              #{ticket.id}
            </Text>
          </div>
          <Badge>{ticket.status}</Badge>
        </Group>
        <Text size="sm" lineClamp={3}>
          {ticket.body}
        </Text>
        <Group gap="xs">
          <Badge variant="light">{ticket.department}</Badge>
          <Badge variant="light">P{ticket.user_priority}</Badge>
          {ticket.ai_confidence !== null && ticket.ai_confidence !== undefined && (
            <ConfidenceBadge confidence={ticket.ai_confidence} />
          )}
        </Group>
        {ticket.agent_id && (
          <Text size="xs" c="dimmed">
            Агент #{ticket.agent_id}
          </Text>
        )}
      </Stack>
    </Paper>
  );
}
