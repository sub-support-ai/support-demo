import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type {
  Ticket,
  TicketComment,
  TicketCommentCreate,
  TicketDraftUpdate,
  TicketFeedbackPayload,
} from "./types";

function updateTicketInCache(queryClient: ReturnType<typeof useQueryClient>, ticket: Ticket) {
  queryClient.setQueryData<Ticket[]>(["tickets"], (current) =>
    current?.map((item) => (item.id === ticket.id ? ticket : item)) ?? current,
  );
  queryClient.setQueryData(["tickets", ticket.id], ticket);
}

export function useTickets() {
  return useQuery({
    queryKey: ["tickets"],
    queryFn: async () => {
      const { data } = await api.get<Ticket[]>("/tickets/");
      return data;
    },
  });
}

export function useConfirmTicket() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (ticketId: number) => {
      const { data } = await api.patch<Ticket>(`/tickets/${ticketId}/confirm`);
      return data;
    },
    onSuccess: (ticket) => {
      updateTicketInCache(queryClient, ticket);
    },
  });
}

export function useUpdateTicketDraft() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      ticketId,
      payload,
    }: {
      ticketId: number;
      payload: TicketDraftUpdate;
    }) => {
      const { data } = await api.patch<Ticket>(
        `/tickets/${ticketId}/draft`,
        payload,
      );
      return data;
    },
    onSuccess: (ticket) => {
      updateTicketInCache(queryClient, ticket);
    },
  });
}

export function useUpdateTicketStatus() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      ticketId,
      status,
    }: {
      ticketId: number;
      status: string;
    }) => {
      const { data } = await api.patch<Ticket>(`/tickets/${ticketId}`, { status });
      return data;
    },
    onSuccess: (ticket) => {
      updateTicketInCache(queryClient, ticket);
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

export function useResolveTicket() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (ticketId: number) => {
      const { data } = await api.patch<Ticket>(`/tickets/${ticketId}/resolve`, {
        agent_accepted_ai_response: false,
      });
      return data;
    },
    onSuccess: (ticket) => {
      updateTicketInCache(queryClient, ticket);
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

export function useTicketComments(ticketId?: number, enabled = false) {
  return useQuery({
    queryKey: ["tickets", ticketId, "comments"],
    queryFn: async () => {
      const { data } = await api.get<TicketComment[]>(
        `/tickets/${ticketId}/comments`,
      );
      return data;
    },
    enabled: Boolean(ticketId) && enabled,
  });
}

export function useCreateTicketComment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      ticketId,
      payload,
    }: {
      ticketId: number;
      payload: TicketCommentCreate;
    }) => {
      const { data } = await api.post<TicketComment>(
        `/tickets/${ticketId}/comments`,
        payload,
      );
      return data;
    },
    onSuccess: (_comment, variables) => {
      queryClient.invalidateQueries({
        queryKey: ["tickets", variables.ticketId, "comments"],
      });
    },
  });
}

export function useSubmitTicketFeedback() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      ticketId,
      payload,
    }: {
      ticketId: number;
      payload: TicketFeedbackPayload;
    }) => {
      const { data } = await api.patch<Ticket>(
        `/tickets/${ticketId}/feedback`,
        payload,
      );
      return data;
    },
    onSuccess: (ticket) => {
      updateTicketInCache(queryClient, ticket);
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}
