import {
  Alert,
  Badge,
  Button,
  Group,
  Paper,
  Stack,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { IconCheck, IconMessageCircle, IconPlayerPlay } from "@tabler/icons-react";
import { useState } from "react";

import { getApiError } from "../../api/client";
import {
  useCreateTicketComment,
  useResolveTicket,
  useTicketComments,
  useUpdateTicketStatus,
} from "../../api/tickets";
import type { Ticket, UserRole } from "../../api/types";
import {
  getStatusLabel,
  getTicketPriorityLabel,
} from "../../lib/ticketLabels";

function getCorrectionLagSeconds(createdAt: string): number {
  const createdTime = new Date(createdAt).getTime();
  if (Number.isNaN(createdTime)) {
    return 0;
  }
  return Math.max(0, Math.round((Date.now() - createdTime) / 1000));
}

function formatDateTime(value?: string | null): string | null {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
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
  const createComment = useCreateTicketComment();
  const [commentsOpen, setCommentsOpen] = useState(false);
  const [commentText, setCommentText] = useState("");
  const comments = useTicketComments(ticket.id, commentsOpen);
  const canOperate =
    (currentUserRole === "agent" || currentUserRole === "admin") &&
    ticket.status !== "pending_user" &&
    ticket.confirmed_by_user &&
    ticket.status !== "closed" &&
    ticket.status !== "resolved";
  const canComment = (currentUserRole === "agent" || currentUserRole === "admin") &&
    ticket.confirmed_by_user;
  const mutationError =
    updateStatus.error ?? resolveTicket.error ?? createComment.error ?? comments.error;
  const slaDeadline = formatDateTime(ticket.sla_deadline_at);

  async function handleCreateComment() {
    const content = commentText.trim();
    if (!content) {
      return;
    }
    await createComment.mutateAsync({
      ticketId: ticket.id,
      payload: { content, internal: true },
    });
    setCommentText("");
  }

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
          {ticket.request_type && (
            <Badge variant="light">{ticket.request_type}</Badge>
          )}
          {slaDeadline && (
            <Badge color={ticket.is_sla_breached ? "red" : "yellow"} variant="light">
              SLA {ticket.is_sla_breached ? "просрочен" : "до"} {slaDeadline}
            </Badge>
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
        {canComment && (
          <Stack gap="xs">
            <Group justify="flex-end">
              <Button
                size="xs"
                variant="subtle"
                leftSection={<IconMessageCircle size={14} />}
                onClick={() => setCommentsOpen((value) => !value)}
              >
                Комментарии
              </Button>
            </Group>
            {commentsOpen && (
              <Stack gap="xs" className="ticket-comments">
                {comments.data?.length ? (
                  comments.data.map((comment) => (
                    <div className="ticket-comment" key={comment.id}>
                      <Group justify="space-between" gap="xs">
                        <Text size="xs" fw={600}>
                          {comment.author_username ?? "Сотрудник"}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {formatDateTime(comment.created_at)}
                        </Text>
                      </Group>
                      <Text size="sm">{comment.content}</Text>
                    </div>
                  ))
                ) : (
                  <Text size="sm" c="dimmed">
                    Комментариев пока нет.
                  </Text>
                )}
                <Textarea
                  value={commentText}
                  minRows={2}
                  maxRows={5}
                  autosize
                  maxLength={2000}
                  placeholder="Добавить рабочий комментарий"
                  onChange={(event) => setCommentText(event.currentTarget.value)}
                />
                <Group justify="flex-end">
                  <Button
                    size="xs"
                    loading={createComment.isPending}
                    disabled={!commentText.trim()}
                    onClick={handleCreateComment}
                  >
                    Добавить
                  </Button>
                </Group>
              </Stack>
            )}
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}
