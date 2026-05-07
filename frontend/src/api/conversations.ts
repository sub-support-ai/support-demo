import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type {
  Conversation,
  EscalateResponse,
  EscalationContext,
  Message,
} from "./types";

export function useConversations() {
  return useQuery({
    queryKey: ["conversations"],
    queryFn: async () => {
      const { data } = await api.get<Conversation[]>("/conversations/");
      return data;
    },
    refetchInterval: (query) => {
      if (document.visibilityState !== "visible") {
        return false;
      }
      const data = query.state.data;
      return data?.some((conversation) => conversation.status === "ai_processing")
        ? 2000
        : false;
    },
  });
}

export function useCreateConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data } = await api.post<Conversation>("/conversations/");
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}

export function useMessages(conversationId?: number, aiProcessing = false) {
  return useQuery({
    queryKey: ["conversations", conversationId, "messages"],
    queryFn: async () => {
      const { data } = await api.get<Message[]>(
        `/conversations/${conversationId}/messages`,
      );
      return data;
    },
    enabled: Boolean(conversationId),
    refetchInterval:
      aiProcessing && document.visibilityState === "visible" ? 2000 : false,
  });
}

export function useSendMessage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      conversationId,
      content,
    }: {
      conversationId: number;
      content: string;
    }) => {
      const { data } = await api.post<Message[]>(
        `/conversations/${conversationId}/messages`,
        { content },
      );
      return data;
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: ["conversations", variables.conversationId, "messages"],
      });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}

export function useEscalateConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      conversationId,
      context,
    }: {
      conversationId: number;
      context: EscalationContext;
    }) => {
      const { data } = await api.post<EscalateResponse>(
        `/conversations/${conversationId}/escalate`,
        { context },
      );
      return data;
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({
        queryKey: ["conversations", data.conversation_id, "messages"],
      });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
    },
  });
}
