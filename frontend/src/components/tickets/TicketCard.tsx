import { Badge, Group, Paper, Stack, Text, Title } from "@mantine/core";

import type { Ticket } from "../../api/types";
import {
  getStatusLabel,
  getTicketPriorityLabel,
} from "../../lib/ticketLabels";
import { ConfidenceBadge } from "../chat/ConfidenceBadge";

export function TicketCard({ ticket }: { ticket: Ticket }) {
  return (
    <Paper className="ticket-card" withBorder>
      <Stack gap="xs">
        <Group justify="space-between" align="start">
          <div>
            <Title order={4}>{ticket.title}</Title>
          </div>
          <Badge>{getStatusLabel(ticket.status)}</Badge>
        </Group>
        <Text size="sm" lineClamp={3}>
          {ticket.body}
        </Text>
        {(ticket.requester_name || ticket.office || ticket.affected_item) && (
          <Text size="xs" c="dimmed">
            {[ticket.requester_name, ticket.office, ticket.affected_item]
              .filter(Boolean)
              .join(" · ")}
          </Text>
        )}
        <Group gap="xs">
          <Badge variant="light">{ticket.department}</Badge>
          <Badge variant="light">{getTicketPriorityLabel(ticket)}</Badge>
          {ticket.ai_confidence !== null &&
            ticket.ai_confidence !== undefined &&
            ticket.ai_confidence > 0 && (
            <ConfidenceBadge confidence={ticket.ai_confidence} />
          )}
        </Group>
      </Stack>
    </Paper>
  );
}
