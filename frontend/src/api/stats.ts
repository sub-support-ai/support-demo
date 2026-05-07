import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type {
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
