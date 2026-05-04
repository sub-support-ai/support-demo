import { useQuery } from "@tanstack/react-query";

import { api } from "./client";
import type { StatsResponse } from "./types";

export function useStats() {
  return useQuery({
    queryKey: ["stats"],
    queryFn: async () => {
      const { data } = await api.get<StatsResponse>("/stats/");
      return data;
    },
  });
}
