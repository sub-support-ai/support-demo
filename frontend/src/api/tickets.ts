import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type {
  ResolveTicketPayload,
  Ticket,
  TicketDraftUpdate,
  TicketStatusUpdate,
} from "./types";

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
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      queryClient.invalidateQueries({ queryKey: ["tickets", ticket.id] });
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
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      queryClient.invalidateQueries({ queryKey: ["tickets", ticket.id] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}
