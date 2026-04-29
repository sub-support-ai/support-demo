import {
  Alert,
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
import { useConfirmTicket, useTickets } from "../api/tickets";
import type { Ticket } from "../api/types";
import { Composer } from "../components/chat/Composer";
import { MessageBubble } from "../components/chat/MessageBubble";
import { PrefilledTicketPanel } from "../components/tickets/PrefilledTicketPanel";

export function ChatPage() {
  const conversations = useConversations();
  const createConversation = useCreateConversation();
  const sendMessage = useSendMessage();
  const escalate = useEscalateConversation();
  const confirmTicket = useConfirmTicket();
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
    if (activeConversationId) {
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

  async function handleEscalate() {
    if (!activeConversationId) {
      return;
    }
    try {
      const response = await escalate.mutateAsync(activeConversationId);
      setDraftTicket(response.ticket);
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

  const error =
    conversations.error ||
    messages.error ||
    sendMessage.error ||
    escalate.error ||
    confirmTicket.error ||
    createConversation.error ||
    tickets.error;

  return (
    <div className="page-grid">
      <Paper className="chat-panel" withBorder>
        <Group justify="space-between" mb="md">
          <div>
            <Title order={2}>Чат поддержки</Title>
            <Text size="sm" c="dimmed">
              {activeConversation
                ? `Диалог #${activeConversation.id} · ${activeConversation.status}`
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
                  escalationLoading={escalate.isPending}
                  onEscalate={handleEscalate}
                />
              ))}
              <div ref={bottomRef} />
            </Stack>
          </ScrollArea>
          <Composer
            loading={sendMessage.isPending || createConversation.isPending}
            disabled={activeConversation?.status === "escalated"}
            onSend={handleSend}
          />
        </div>
      </Paper>

      <div className="side-panel">
        {activeTicket ? (
          <PrefilledTicketPanel
            ticket={activeTicket}
            confirmLoading={confirmTicket.isPending}
            onConfirm={handleConfirm}
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
