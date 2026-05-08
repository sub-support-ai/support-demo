import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type {
  AIFallbacksStats,
  AIJob,
  FailedJobsResponse,
  JobKind,
  JobStatusFilter,
  JobsResponse,
  KnowledgeEmbeddingJob,
  StatsResponse,
} from "./types";

export function useStats() {
  return useQuery({
    queryKey: ["stats"],
    queryFn: async () => {
      const { data } = await api.get<StatsResponse>("/stats/");
      return data;
    },
  });
}

export function useAIFallbacksStats(enabled: boolean) {
  return useQuery({
    queryKey: ["stats", "ai", "fallbacks"],
    queryFn: async () => {
      // Без since бэкенд использует дефолтное окно 24 ч — этого достаточно
      // для виджета «Сбои AI за 24ч». Глубже окно админ может посмотреть
      // отдельным запросом, но для дашборда лишний шум.
      const { data } = await api.get<AIFallbacksStats>("/stats/ai/fallbacks");
      return data;
    },
    enabled,
    // 30 сек: достаточно частое обновление, чтобы заметить новый сбой,
    // но не нагружает БД при долго открытой вкладке.
    refetchInterval: enabled ? 30000 : false,
    refetchIntervalInBackground: false,
  });
}

export function useFailedJobs(enabled: boolean) {
  return useQuery({
    queryKey: ["jobs", "failed"],
    queryFn: async () => {
      const { data } = await api.get<FailedJobsResponse>("/jobs/failed");
      return data;
    },
    enabled,
  });
}

export function useJobs({
  enabled,
  kind,
  status,
}: {
  enabled: boolean;
  kind: JobKind;
  status: JobStatusFilter;
}) {
  return useQuery({
    queryKey: ["jobs", kind, status],
    queryFn: async () => {
      const { data } = await api.get<JobsResponse>("/jobs/", {
        params: { kind, status, limit: 50 },
      });
      return data;
    },
    enabled,
    // Авто-обновление каждые 5 секунд: страница — оперативный мониторинг
    // зависших задач, поэтому ручной refresh здесь UX-провал. При
    // невидимой вкладке React Query сам останавливает polling.
    refetchInterval: enabled ? 5000 : false,
    refetchIntervalInBackground: false,
  });
}

export function useRetryAIJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (jobId: number) => {
      const { data } = await api.post<AIJob>(`/jobs/ai/${jobId}/retry`);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs", "failed"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}

export function useRequeueAIJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (jobId: number) => {
      const { data } = await api.post<AIJob>(`/jobs/ai/${jobId}/requeue`);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}

export function useRetryKnowledgeEmbeddingJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (jobId: number) => {
      const { data } = await api.post<KnowledgeEmbeddingJob>(
        `/jobs/knowledge-embeddings/${jobId}/retry`,
      );
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs", "failed"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
      queryClient.invalidateQueries({ queryKey: ["knowledge", "articles"] });
    },
  });
}

export function useRequeueKnowledgeEmbeddingJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (jobId: number) => {
      const { data } = await api.post<KnowledgeEmbeddingJob>(
        `/jobs/knowledge-embeddings/${jobId}/requeue`,
      );
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
      queryClient.invalidateQueries({ queryKey: ["knowledge", "articles"] });
    },
  });
}
