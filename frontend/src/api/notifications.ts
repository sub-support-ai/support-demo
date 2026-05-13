import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type { AppNotification, NotificationUnreadCount } from "./types";

export function useNotificationUnreadCount(enabled = true) {
  return useQuery({
    queryKey: ["notifications", "unread-count"],
    enabled,
    refetchInterval: 15000,
    queryFn: async () => {
      const { data } = await api.get<NotificationUnreadCount>(
        "/notifications/unread-count",
      );
      return data;
    },
  });
}

export function useNotifications(enabled = true) {
  return useQuery({
    queryKey: ["notifications"],
    enabled,
    queryFn: async () => {
      const { data } = await api.get<AppNotification[]>("/notifications/", {
        params: { limit: 10 },
      });
      return data;
    },
  });
}

export function useMarkNotificationRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (notificationId: number) => {
      const { data } = await api.patch<AppNotification>(
        `/notifications/${notificationId}/read`,
      );
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}

export function useMarkAllNotificationsRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data } = await api.patch<NotificationUnreadCount>(
        "/notifications/read-all",
      );
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}
