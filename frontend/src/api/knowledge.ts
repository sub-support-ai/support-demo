import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type { KnowledgeFeedbackPayload } from "./types";

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
