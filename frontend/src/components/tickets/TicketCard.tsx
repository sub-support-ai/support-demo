import {
  Alert,
  Badge,
  Button,
  Group,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconCheck, IconPlayerPlay } from "@tabler/icons-react";

import { getApiError } from "../../api/client";
import { useResolveTicket, useUpdateTicketStatus } from "../../api/tickets";
import type { Ticket, UserRole } from "../../api/types";
import {
  getStatusLabel,
  getTicketPriorityLabel,
} from "../../lib/ticketLabels";
import { ConfidenceBadge } from "../chat/ConfidenceBadge";

function getCorrectionLagSeconds(createdAt: string): number {
  const createdTime = new Date(createdAt).getTime();
  if (Number.isNaN(createdTime)) {
    return 0;
  }
  return Math.max(0, Math.round((Date.now() - createdTime) / 1000));
}

export function TicketCard({
  ticket,
  currentUserRole,
}: {
  ticket: Ticket;
  currentUserRole?: UserRole;
}) {
  const updateStatus = useUpdateTicketStatus();
  const resolveTicket = useResolveTicket();
  const canOperate =
    (currentUserRole === "agent" || currentUserRole === "admin") &&
    ticket.status !== "pending_user" &&
    ticket.confirmed_by_user &&
    ticket.status !== "closed" &&
    ticket.status !== "resolved";
  const mutationError = updateStatus.error ?? resolveTicket.error;

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
        {mutationError && (
          <Alert color="red" variant="light">
            {getApiError(mutationError)}
          </Alert>
        )}
        {canOperate && (
          <Group gap="xs" justify="flex-end">
            {ticket.status !== "in_progress" && (
              <Button
                size="xs"
                variant="light"
                leftSection={<IconPlayerPlay size={14} />}
                loading={updateStatus.isPending}
                onClick={() =>
                  updateStatus.mutate({
                    ticketId: ticket.id,
                    payload: { status: "in_progress" },
                  })
                }
              >
                В работу
              </Button>
            )}
            <Button
              size="xs"
              color="green"
              leftSection={<IconCheck size={14} />}
              loading={resolveTicket.isPending}
              onClick={() =>
                resolveTicket.mutate({
                  ticketId: ticket.id,
                  payload: {
                    agent_accepted_ai_response: true,
                    correction_lag_seconds: getCorrectionLagSeconds(
                      ticket.created_at,
                    ),
                  },
                })
              }
            >
              Закрыть
            </Button>
          </Group>
        )}
      </Stack>
    </Paper>
  );
}
