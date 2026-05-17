import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type {
  KnowledgeArticle,
  KnowledgeArticlePayload,
  KnowledgeEmbeddingJob,
  KnowledgeFeedbackPayload,
} from "./types";

export function useKnowledgeArticles(activeOnly = false) {
  return useQuery({
    queryKey: ["knowledge", "articles", activeOnly],
    queryFn: async () => {
      const { data } = await api.get<KnowledgeArticle[]>("/knowledge/", {
        params: { active_only: activeOnly },
      });
      return data;
    },
  });
}

export function useCreateKnowledgeArticle() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: KnowledgeArticlePayload) => {
      const { data } = await api.post<KnowledgeArticle>("/knowledge/", payload);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge", "articles"] });
    },
  });
}

export function useUpdateKnowledgeArticle() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      articleId,
      payload,
    }: {
      articleId: number;
      payload: Partial<KnowledgeArticlePayload>;
    }) => {
      const { data } = await api.patch<KnowledgeArticle>(
        `/knowledge/${articleId}`,
        payload,
      );
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge", "articles"] });
    },
  });
}

export function useReindexKnowledgeArticle() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (articleId: number) => {
      const { data } = await api.post<KnowledgeEmbeddingJob>(
        `/knowledge/${articleId}/reindex`,
      );
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge", "articles"] });
    },
  });
}

export function useReindexAllKnowledgeArticles() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data } = await api.post<KnowledgeEmbeddingJob>("/knowledge/reindex");
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge", "articles"] });
    },
  });
}

export function useSuppressKnowledgeArticle() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (articleId: number) => {
      const { data } = await api.post<KnowledgeArticle>(`/knowledge/${articleId}/suppress`);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge", "articles"] });
    },
  });
}

export function useRestoreKnowledgeArticle() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (articleId: number) => {
      const { data } = await api.post<KnowledgeArticle>(`/knowledge/${articleId}/restore`);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge", "articles"] });
    },
  });
}

export function useSubmitKnowledgeFeedback() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: KnowledgeFeedbackPayload) => {
      const { data } = await api.post("/knowledge/feedback", payload);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}
