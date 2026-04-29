import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useQueryClient } from "@tanstack/react-query";

import { tokenStorage } from "../api/client";

interface AuthContextValue {
  token: string | null;
  setToken: (token: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [token, setTokenState] = useState<string | null>(() => tokenStorage.get());

  const setToken = useCallback((nextToken: string) => {
    tokenStorage.set(nextToken);
    setTokenState(nextToken);
  }, []);

  const logout = useCallback(() => {
    tokenStorage.clear();
    setTokenState(null);
    queryClient.clear();
  }, [queryClient]);

  useEffect(() => {
    window.addEventListener("tp-auth-expired", logout);
    return () => window.removeEventListener("tp-auth-expired", logout);
  }, [logout]);

  const value = useMemo(
    () => ({ token, setToken, logout }),
    [token, setToken, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return ctx;
}
