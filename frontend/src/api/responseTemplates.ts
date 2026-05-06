import { useQuery } from "@tanstack/react-query";

import { api } from "./client";
import type { ResponseTemplate } from "./types";

export function useResponseTemplates({
  department,
  requestType,
  enabled,
}: {
  department?: string | null;
  requestType?: string | null;
  enabled: boolean;
}) {
  return useQuery({
    queryKey: ["response-templates", department, requestType],
    queryFn: async () => {
      const { data } = await api.get<ResponseTemplate[]>("/response-templates/", {
        params: {
          department,
          request_type: requestType,
        },
      });
      return data;
    },
    enabled,
  });
}
