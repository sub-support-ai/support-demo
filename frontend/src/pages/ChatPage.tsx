import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
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
  useDeclineTicket,
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
    return "Диалог без запроса";
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
  const declineTicket = useDeclineTicket();
  const updateTicketDraft = useUpdateTicketDraft();
  const tickets = useTickets();
  const [activeConversationId, setActiveConversationId] = useState<number>();
  const [draftTicket, setDraftTicket] = useState<Ticket | null>(null);
  const [awaitingAiConversationId, setAwaitingAiConversationId] =
    useState<number>();
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
  const isAiProcessing = activeConversation?.status === "ai_processing";
  const isAwaitingAiResponse =
    awaitingAiConversationId !== undefined &&
    awaitingAiConversationId === activeConversationId;
  const shouldPollMessages = isAiProcessing || isAwaitingAiResponse;

  // Метки для каждой стадии обработки (пользователь не знает, что это «псевдо»).
  const AI_STAGE_LABELS: Record<string, string> = {
    thinking: "Анализирую вопрос...",
    searching: "Ищу в базе знаний...",
    found_kb: "Нашёл подходящую статью...",
    generating: "Формирую ответ...",
  };
  const aiStageLabel = shouldPollMessages
    ? (activeConversation?.ai_stage
        ? (AI_STAGE_LABELS[activeConversation.ai_stage] ?? "Обрабатываю запрос...")
        : "Обрабатываю запрос...")
    : "";
  const composerDisabled =
    activeConversation?.status === "escalated" ||
    hasPendingDraft ||
    shouldPollMessages;

  useEffect(() => {
    if (!activeConversationId && conversations.data?.length) {
      setActiveConversationId(conversations.data[0].id);
    }
  }, [activeConversationId, conversations.data]);

  const messages = useMessages(activeConversationId, shouldPollMessages);

  useEffect(() => {
    if (!isAwaitingAiResponse) {
      return;
    }

    let latestUserMessageId = 0;
    let latestAiMessageId = 0;
    for (const message of messages.data ?? []) {
      if (message.role === "user") {
        latestUserMessageId = Math.max(latestUserMessageId, message.id);
      }
      if (message.role === "ai") {
        latestAiMessageId = Math.max(latestAiMessageId, message.id);
      }
    }

    if (latestUserMessageId > 0 && latestAiMessageId > latestUserMessageId) {
      setAwaitingAiConversationId(undefined);
    }
  }, [isAwaitingAiResponse, messages.data]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.data?.length, shouldPollMessages]);

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
      const response = await sendMessage.mutateAsync({ conversationId, content });
      if (response.ai_job_id !== null && response.ai_job_id !== undefined) {
        setAwaitingAiConversationId(conversationId);
      } else {
        setAwaitingAiConversationId(undefined);
      }
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

  async function handleDecline() {
    if (!activeTicket) {
      return;
    }
    try {
      const ticket = await declineTicket.mutateAsync(activeTicket.id);
      setDraftTicket(ticket);
      await conversations.refetch();
    } catch {
      // Ошибка уже хранится в mutation state и показывается в Alert.
    }
  }

  async function handleSaveDraft(payload: TicketDraftUpdate) {
    if (!activeTicket) {
      return;
    }
    try {
      const ticket = await updateTicketDraft.mutateAsync({
        ticketId: activeTicket.id,
        payload,
      });
      setDraftTicket(ticket);
    } catch {
      // Ошибка уже хранится в mutation state и показывается в Alert.
    }
  }

  const error =
    conversations.error ||
    messages.error ||
    sendMessage.error ||
    escalate.error ||
    confirmTicket.error ||
    declineTicket.error ||
    updateTicketDraft.error ||
    createConversation.error ||
    me.error ||
    tickets.error;
  const requestContext = me.data?.request_context ?? null;
  const showAiConfidence =
    me.data?.role === "agent" || me.data?.role === "admin";

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

        <div className="chat-surface">
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
                  showAiConfidence={showAiConfidence}
                  onEscalate={handleEscalate}
                />
              ))}
              {shouldPollMessages && (
                <Group className="ai-processing-indicator" gap="xs">
                  <Loader size="xs" />
                  <Text size="sm" c="dimmed">
                    {aiStageLabel}
                  </Text>
                </Group>
              )}
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
        <Paper withBorder p="md" className="quiet-panel conversations-panel">
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
            declineLoading={declineTicket.isPending}
            saveLoading={updateTicketDraft.isPending}
            onConfirm={handleConfirm}
            onDecline={handleDecline}
            onSave={handleSaveDraft}
          />
        ) : (
          <Paper withBorder p="md" className="quiet-panel">
            <Title order={4}>Черновик запроса</Title>
            <Text size="sm" c="dimmed">
              Появится после эскалации диалога.
            </Text>
          </Paper>
        )}
      </div>
    </div>
  );
}
