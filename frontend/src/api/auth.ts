import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, tokenStorage } from "./client";
import type { TokenResponse, UserMe } from "./types";

export interface LoginPayload {
  username: string;
  password: string;
}

export interface RegisterPayload {
  email: string;
  username: string;
  password: string;
}

export function useMe(enabled: boolean) {
  return useQuery({
    queryKey: ["auth", "me"],
    queryFn: async () => {
      const { data } = await api.get<UserMe>("/auth/me");
      return data;
    },
    enabled,
  });
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: LoginPayload) => {
      const form = new URLSearchParams();
      form.set("username", payload.username);
      form.set("password", payload.password);
      const { data } = await api.post<TokenResponse>("/auth/login", form, {
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
      });
      return data;
    },
    onSuccess: (data) => {
      tokenStorage.set(data.access_token);
      queryClient.invalidateQueries({ queryKey: ["auth"] });
    },
  });
}

export function useRegister() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: RegisterPayload) => {
      const { data } = await api.post<TokenResponse>("/auth/register", payload);
      return data;
    },
    onSuccess: (data) => {
      tokenStorage.set(data.access_token);
      queryClient.invalidateQueries({ queryKey: ["auth"] });
    },
  });
}
