import {
  Alert,
  Badge,
  Button,
  Group,
  LoadingOverlay,
  Paper,
  ScrollArea,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconMessageCircle, IconPlus } from "@tabler/icons-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  useConversations,
  useCreateConversation,
  useEscalateConversation,
  useMessages,
  useSendMessage,
} from "../api/conversations";
import { getApiError } from "../api/client";
import { useMe } from "../api/auth";
import {
  useConfirmTicket,
  useTickets,
  useUpdateTicketDraft,
} from "../api/tickets";
import type {
  Conversation,
  EscalationContext,
  Ticket,
  TicketDraftUpdate,
} from "../api/types";
import { Composer } from "../components/chat/Composer";
import { MessageBubble } from "../components/chat/MessageBubble";
import { PrefilledTicketPanel } from "../components/tickets/PrefilledTicketPanel";
import { getStatusLabel } from "../lib/ticketLabels";
import { useAuth } from "../stores/auth";

function formatConversationDate(value?: string | null) {
  if (!value) {
    return "Старый диалог";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Старый диалог";
  }

  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function getConversationDate(conversation: Conversation, tickets?: Ticket[]) {
  const ticket = tickets?.find((item) => item.conversation_id === conversation.id);
  return formatConversationDate(
    conversation.created_at ??
      conversation.updated_at ??
      ticket?.created_at ??
      ticket?.updated_at,
  );
}

function getConversationTitle(conversation: Conversation, tickets?: Ticket[]) {
  const ticket = tickets?.find((item) => item.conversation_id === conversation.id);
  if (ticket?.title) {
    return ticket.title;
  }

  if (conversation.status === "active") {
    return "Диалог без тикета";
  }

  return getStatusLabel(conversation.status);
}

export function ChatPage() {
  const { token } = useAuth();
  const me = useMe(Boolean(token));
  const conversations = useConversations();
  const createConversation = useCreateConversation();
  const sendMessage = useSendMessage();
  const escalate = useEscalateConversation();
  const confirmTicket = useConfirmTicket();
  const updateTicketDraft = useUpdateTicketDraft();
  const tickets = useTickets();
  const [activeConversationId, setActiveConversationId] = useState<number>();
  const [draftTicket, setDraftTicket] = useState<Ticket | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const activeConversation = useMemo(() => {
    return conversations.data?.find((item) => item.id === activeConversationId);
  }, [activeConversationId, conversations.data]);

  const restoredTicket = useMemo(() => {
    if (!activeConversationId) {
      return null;
    }

    return (
      tickets.data
        ?.filter((ticket) => ticket.conversation_id === activeConversationId)
        .sort(
          (left, right) =>
            new Date(right.created_at).getTime() -
            new Date(left.created_at).getTime(),
        )[0] ?? null
    );
  }, [activeConversationId, tickets.data]);

  const activeTicket =
    draftTicket?.conversation_id === activeConversationId
      ? draftTicket
      : restoredTicket;
  const hasPendingDraft =
    activeTicket !== null &&
    activeTicket.status === "pending_user" &&
    !activeTicket.confirmed_by_user;
  const composerDisabled =
    activeConversation?.status === "escalated" || hasPendingDraft;

  useEffect(() => {
    if (!activeConversationId && conversations.data?.length) {
      setActiveConversationId(conversations.data[0].id);
    }
  }, [activeConversationId, conversations.data]);

  const messages = useMessages(activeConversationId);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.data?.length]);

  async function ensureConversation() {
    const activeConversationExists =
      activeConversationId &&
      (
        !conversations.data ||
        conversations.data.some((item) => item.id === activeConversationId)
      );
    if (activeConversationExists) {
      return activeConversationId;
    }
    const conversation = await createConversation.mutateAsync();
    setActiveConversationId(conversation.id);
    return conversation.id;
  }

  async function handleSend(content: string) {
    try {
      const conversationId = await ensureConversation();
      await sendMessage.mutateAsync({ conversationId, content });
    } catch {
      // Ошибка уже хранится в mutation/query state и показывается в Alert.
    }
  }

  async function handleNewConversation() {
    try {
      const conversation = await createConversation.mutateAsync();
      setDraftTicket(null);
      setActiveConversationId(conversation.id);
    } catch {
      // Ошибка уже хранится в mutation state и показывается в Alert.
    }
  }

  async function handleEscalate(conversationId: number, context: EscalationContext) {
    try {
      const response = await escalate.mutateAsync({
        conversationId,
        context,
      });
      setDraftTicket(response.ticket);
      setActiveConversationId(conversationId);
    } catch {
      // Ошибка уже хранится в mutation state и показывается в Alert.
    }
  }

  async function handleConfirm() {
    if (!activeTicket) {
      return;
    }
    try {
      const ticket = await confirmTicket.mutateAsync(activeTicket.id);
      setDraftTicket(ticket);
    } catch {
      // Ошибка уже хранится в mutation state и показывается в Alert.
    }
  }

  async function handleSaveDraft(payload: TicketDraftUpdate) {
    if (!activeTicket) {
      return;
    }
    const ticket = await updateTicketDraft.mutateAsync({
      ticketId: activeTicket.id,
      payload,
    });
    setDraftTicket(ticket);
  }

  const error =
    conversations.error ||
    messages.error ||
    sendMessage.error ||
    escalate.error ||
    confirmTicket.error ||
    updateTicketDraft.error ||
    createConversation.error ||
    me.error ||
    tickets.error;
  const requestContext = me.data?.request_context ?? null;

  return (
    <div className="page-grid">
      <Paper className="chat-panel" withBorder>
        <Group justify="space-between" mb="md">
          <div>
            <Title order={2}>Чат поддержки</Title>
            <Text size="sm" c="dimmed">
              {activeConversation
                ? getStatusLabel(activeConversation.status)
                : "Новый диалог"}
            </Text>
          </div>
          <Button
            variant="light"
            leftSection={<IconPlus size={16} />}
            loading={createConversation.isPending}
            onClick={handleNewConversation}
          >
            Новый
          </Button>
        </Group>

        {error && (
          <Alert color="red" variant="light" mb="md">
            {getApiError(error)}
          </Alert>
        )}

        <div className={`chat-surface${activeTicket ? " has-draft" : ""}`}>
          <LoadingOverlay visible={messages.isFetching && !messages.data} />
          <ScrollArea className="messages-scroll" type="auto">
            <Stack gap="sm" p="md">
              {!messages.data?.length && (
                <div className="empty-state">
                  <IconMessageCircle size={34} />
                  <Text fw={600}>Нет сообщений</Text>
                </div>
              )}
              {messages.data?.map((message) => (
                <MessageBubble
                  key={message.id}
                  message={message}
                  escalationDisabled={composerDisabled}
                  escalationLoading={escalate.isPending}
                  contextDefaults={requestContext}
                  onEscalate={handleEscalate}
                />
              ))}
              <div ref={bottomRef} />
            </Stack>
          </ScrollArea>
          <Composer
            loading={sendMessage.isPending || createConversation.isPending}
            disabled={composerDisabled}
            onSend={handleSend}
          />
        </div>
      </Paper>

      <div className="side-panel">
        <Paper withBorder p="md" className="quiet-panel">
          <Group justify="space-between" mb="sm">
            <Title order={4}>Диалоги</Title>
            <Badge variant="light">{conversations.data?.length ?? 0}</Badge>
          </Group>
          <Stack gap="xs" className="conversation-list">
            {conversations.data?.length ? (
              conversations.data.map((conversation) => (
                <button
                  key={conversation.id}
                  type="button"
                  className={`conversation-item${
                    conversation.id === activeConversationId ? " active" : ""
                  }`}
                  onClick={() => {
                    setDraftTicket(null);
                    setActiveConversationId(conversation.id);
                  }}
                >
                  <Text className="conversation-item-title" lineClamp={2}>
                    {getConversationTitle(conversation, tickets.data)}
                  </Text>
                  <Group justify="space-between" gap="xs" wrap="nowrap">
                    <Badge size="sm" variant="light">
                      {getStatusLabel(conversation.status)}
                    </Badge>
                    <Text size="xs" c="dimmed">
                      {getConversationDate(conversation, tickets.data)}
                    </Text>
                  </Group>
                </button>
              ))
            ) : (
              <Text size="sm" c="dimmed">
                Диалогов пока нет.
              </Text>
            )}
          </Stack>
        </Paper>

        {activeTicket ? (
          <PrefilledTicketPanel
            ticket={activeTicket}
            confirmLoading={confirmTicket.isPending}
            saveLoading={updateTicketDraft.isPending}
            onConfirm={handleConfirm}
            onSave={handleSaveDraft}
          />
        ) : (
          <Paper withBorder p="md" className="quiet-panel">
            <Title order={4}>Черновик тикета</Title>
            <Text size="sm" c="dimmed">
              Появится после эскалации диалога.
            </Text>
          </Paper>
        )}
      </div>
    </div>
  );
}
