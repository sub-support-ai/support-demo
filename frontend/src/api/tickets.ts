import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type {
  ResolveTicketPayload,
  Ticket,
  TicketComment,
  TicketCommentCreate,
  TicketDraftUpdate,
  TicketFeedbackPayload,
  TicketQueue,
  TicketReroutePayload,
  TicketStatus,
  TicketStatusUpdate,
} from "./types";

function updateTicketInCache(
  queryClient: ReturnType<typeof useQueryClient>,
  ticket: Ticket,
) {
  queryClient.setQueryData<Ticket[]>(["tickets"], (current) =>
    current?.map((item) => (item.id === ticket.id ? ticket : item)) ?? current,
  );
  queryClient.setQueryData(["tickets", ticket.id], ticket);
}

export function useTickets(options?: {
  enabled?: boolean;
  refetchInterval?: number;
  queue?: TicketQueue;
  status?: TicketStatus;
  department?: string | null;
  search?: string;
}) {
  const params = {
    queue: options?.queue,
    status: options?.status,
    department: options?.department || undefined,
    search: options?.search?.trim() || undefined,
  };
  return useQuery({
    queryKey: ["tickets", params],
    enabled: options?.enabled,
    refetchInterval: options?.refetchInterval,
    queryFn: async () => {
      const { data } = await api.get<Ticket[]>("/tickets/", { params });
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
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

export function useDeclineTicket() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (ticketId: number) => {
      const { data } = await api.patch<Ticket>(`/tickets/${ticketId}/decline`);
      return data;
    },
    onSuccess: (ticket) => {
      updateTicketInCache(queryClient, ticket);
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
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
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
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

export function useRerouteTicket() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      ticketId,
      payload,
    }: {
      ticketId: number;
      payload: TicketReroutePayload;
    }) => {
      const { data } = await api.patch<Ticket>(
        `/tickets/${ticketId}/reroute`,
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

/** Промоут решённого тикета в черновик KB-статьи. Возвращает id и title
 *  созданной/обновлённой статьи. Доступно агенту/админу.
 *  Backend: POST /tickets/{id}/promote-to-kb (см. routers/tickets.py).
 */
export interface KBPromotionResult {
  article_id: number;
  title: string;
  is_active: boolean;
  created: boolean;
}

export function usePromoteTicketToKb() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (ticketId: number) => {
      const { data } = await api.post<KBPromotionResult>(
        `/tickets/${ticketId}/promote-to-kb`,
      );
      return data;
    },
    onSuccess: () => {
      // KB-список меняется → инвалидируем; tickets не трогаем — статус
      // тикета не изменился.
      queryClient.invalidateQueries({ queryKey: ["knowledge"] });
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

export function useTicketComments(ticketId?: number, enabled = false) {
  return useQuery({
    queryKey: ["tickets", ticketId, "comments"],
    enabled: Boolean(ticketId) && enabled,
    queryFn: async () => {
      const { data } = await api.get<TicketComment[]>(
        `/tickets/${ticketId}/comments`,
      );
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
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}
