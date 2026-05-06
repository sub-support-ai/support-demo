import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Group,
  Paper,
  Select,
  Stack,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { useMemo, useState } from "react";

import { useResponseTemplates } from "../../api/responseTemplates";
import type { ResponseTemplate, Ticket, UserRole } from "../../api/types";
import {
  useCreateTicketComment,
  useResolveTicket,
  useSubmitTicketFeedback,
  useTicketComments,
  useUpdateTicketStatus,
} from "../../api/tickets";
import {
  getStatusLabel,
  getTicketPriorityLabel,
} from "../../lib/ticketLabels";

function formatDateTime(value?: string | null) {
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

function renderTemplate(template: ResponseTemplate, ticket: Ticket) {
  const values: Record<string, string> = {
    requester_name: ticket.requester_name || "коллега",
    requester_email: ticket.requester_email || "",
    office: ticket.office || "офис не указан",
    affected_item: ticket.affected_item || "объект не указан",
    request_type: ticket.request_type || "запрос",
    request_details: ticket.request_details || "детали не указаны",
    department: ticket.department,
    title: ticket.title,
  };

  return template.body.replace(/\{([a-z_]+)\}/g, (_match, key: string) => {
    return values[key] ?? "";
  });
}

export function TicketCard({
  ticket,
  role = "user",
}: {
  ticket: Ticket;
  role?: UserRole;
}) {
  const [commentsOpen, setCommentsOpen] = useState(false);
  const [commentText, setCommentText] = useState("");
  const [internalComment, setInternalComment] = useState(true);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);
  const comments = useTicketComments(ticket.id, commentsOpen);
  const createComment = useCreateTicketComment();
  const updateStatus = useUpdateTicketStatus();
  const resolveTicket = useResolveTicket();
  const feedback = useSubmitTicketFeedback();

  const isOperator = role === "agent" || role === "admin";
  const isOwner = role === "user";
  const isClosed = ticket.status === "closed" || ticket.status === "resolved";
  const canOperatorAct = isOperator && ticket.confirmed_by_user && !isClosed;
  const slaDate = formatDateTime(ticket.sla_deadline_at);
  const templates = useResponseTemplates({
    department: ticket.department,
    requestType: ticket.request_type,
    enabled: commentsOpen && canOperatorAct,
  });

  const templateOptions = useMemo(
    () =>
      templates.data?.map((template) => ({
        value: String(template.id),
        label: template.request_type
          ? `${template.title} · ${template.request_type}`
          : template.title,
      })) ?? [],
    [templates.data],
  );

  async function handleAddComment() {
    const content = commentText.trim();
    if (!content) {
      return;
    }
    await createComment.mutateAsync({
      ticketId: ticket.id,
      payload: {
        content,
        internal: internalComment,
      },
    });
    setCommentText("");
    setSelectedTemplateId(null);
  }

  function handleTemplateSelect(templateId: string | null) {
    setSelectedTemplateId(templateId);
    const template = templates.data?.find((item) => String(item.id) === templateId);
    if (!template) {
      return;
    }
    setCommentText(renderTemplate(template, ticket));
    setInternalComment(false);
  }

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
        {(ticket.request_type || ticket.request_details) && (
          <div className="ticket-form-summary">
            {ticket.request_type && (
              <Text size="xs" fw={600}>
                {ticket.request_type}
              </Text>
            )}
            {ticket.request_details && (
              <Text size="xs" c="dimmed" lineClamp={2}>
                {ticket.request_details}
              </Text>
            )}
          </div>
        )}
        <Group gap="xs">
          <Badge variant="light">{ticket.department}</Badge>
          <Badge variant="light">{getTicketPriorityLabel(ticket)}</Badge>
          {slaDate && (
            <Badge color={ticket.is_sla_breached ? "red" : "gray"} variant="light">
              {ticket.is_sla_breached ? "SLA просрочен" : "SLA до"} {slaDate}
            </Badge>
          )}
          {(ticket.reopen_count ?? 0) > 0 && (
            <Badge color="orange" variant="light">
              Повторно открыт: {ticket.reopen_count}
            </Badge>
          )}
          {ticket.sla_escalated_at && (
            <Badge color="orange" variant="light">
              SLA эскалирован {formatDateTime(ticket.sla_escalated_at)}
            </Badge>
          )}
        </Group>

        {canOperatorAct && (
          <Group gap="xs">
            {ticket.status === "confirmed" && (
              <Button
                size="xs"
                loading={updateStatus.isPending}
                onClick={() =>
                  updateStatus.mutate({ ticketId: ticket.id, status: "in_progress" })
                }
              >
                В работу
              </Button>
            )}
            {ticket.status === "in_progress" && (
              <Button
                size="xs"
                color="teal"
                loading={resolveTicket.isPending}
                onClick={() => resolveTicket.mutate(ticket.id)}
              >
                Закрыть
              </Button>
            )}
            <Button
              size="xs"
              variant="light"
              onClick={() => setCommentsOpen((value) => !value)}
            >
              Комментарии
            </Button>
          </Group>
        )}

        {isOwner && isClosed && (
          <Group gap="xs">
            <Button
              size="xs"
              color="teal"
              loading={feedback.isPending}
              onClick={() =>
                feedback.mutate({
                  ticketId: ticket.id,
                  payload: { feedback: "helped" },
                })
              }
            >
              Помогло
            </Button>
            <Button
              size="xs"
              variant="light"
              color="orange"
              loading={feedback.isPending}
              onClick={() =>
                feedback.mutate({
                  ticketId: ticket.id,
                  payload: { feedback: "not_helped", reopen: true },
                })
              }
            >
              Не помогло, открыть снова
            </Button>
          </Group>
        )}

        {commentsOpen && (
          <Stack className="ticket-comments" gap="xs">
            {comments.data?.length ? (
              comments.data.map((comment) => (
                <Paper key={comment.id} className="ticket-comment" withBorder>
                  <Group justify="space-between" gap="xs">
                    <Text size="xs" fw={600}>
                      {comment.author_username}
                    </Text>
                    <Badge size="xs" variant="light">
                      {comment.internal ? "Внутренний" : "Для пользователя"}
                    </Badge>
                  </Group>
                  <Text size="sm">{comment.content}</Text>
                </Paper>
              ))
            ) : (
              <Text size="sm" c="dimmed">
                Комментариев пока нет.
              </Text>
            )}
            {createComment.error && (
              <Alert color="red" variant="light">
                Не удалось добавить комментарий.
              </Alert>
            )}
            {canOperatorAct && (
              <Select
                placeholder="Вставить шаблон ответа"
                data={templateOptions}
                value={selectedTemplateId}
                clearable
                searchable
                nothingFoundMessage="Шаблонов нет"
                disabled={templates.isLoading || !templateOptions.length}
                onChange={handleTemplateSelect}
              />
            )}
            <Textarea
              value={commentText}
              minRows={2}
              maxRows={5}
              autosize
              placeholder="Кратко зафиксируйте ход работы или решение"
              onChange={(event) => setCommentText(event.currentTarget.value)}
            />
            <Group justify="space-between">
              <Checkbox
                checked={internalComment}
                label="Внутренний комментарий"
                onChange={(event) =>
                  setInternalComment(event.currentTarget.checked)
                }
              />
              <Button
                size="xs"
                loading={createComment.isPending}
                disabled={!commentText.trim()}
                onClick={handleAddComment}
              >
                Добавить
              </Button>
            </Group>
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}
