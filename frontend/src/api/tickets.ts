import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type {
  TicketComment,
  TicketCommentCreate,
  ResolveTicketPayload,
  Ticket,
  TicketDraftUpdate,
  TicketStatusUpdate,
} from "./types";

function updateTicketInCache(
  queryClient: ReturnType<typeof useQueryClient>,
  ticket: Ticket,
) {
  queryClient.setQueryData<Ticket[]>(["tickets"], (current) =>
    current?.map((item) => (item.id === ticket.id ? ticket : item)),
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
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      queryClient.invalidateQueries({
        queryKey: ["tickets", ticket.id],
      });
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
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      queryClient.invalidateQueries({
        queryKey: ["tickets", ticket.id],
      });
    },
  });
}

export function useTicketComments(ticketId: number, enabled: boolean) {
  return useQuery({
    queryKey: ["tickets", ticketId, "comments"],
    enabled,
    queryFn: async () => {
      const { data } = await api.get<TicketComment[]>(`/tickets/${ticketId}/comments`);
      return data;
    },
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
    onSuccess: (comment) => {
      queryClient.invalidateQueries({
        queryKey: ["tickets", comment.ticket_id, "comments"],
      });
    },
  });
}

export function useUpdateTicketStatus() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      ticketId,
      payload,
    }: {
      ticketId: number;
      payload: TicketStatusUpdate;
    }) => {
      const { data } = await api.patch<Ticket>(`/tickets/${ticketId}`, payload);
      return data;
    },
    onSuccess: (ticket) => {
      updateTicketInCache(queryClient, ticket);
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

export function useResolveTicket() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      ticketId,
      payload,
    }: {
      ticketId: number;
      payload: ResolveTicketPayload;
    }) => {
      const { data } = await api.patch<Ticket>(
        `/tickets/${ticketId}/resolve`,
        payload,
      );
      return data;
    },
    onSuccess: (ticket) => {
      updateTicketInCache(queryClient, ticket);
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}
