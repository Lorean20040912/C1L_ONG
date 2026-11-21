import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, hasTokens, saveTokens, type TokenPair } from "../api/client";
import type { User } from "../api/types";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(hasTokens());

  useEffect(() => {
    if (!hasTokens()) return;
    api<User>("/auth/me")
      .then(setUser)
      .catch(() => saveTokens(null))
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await api<TokenPair>("/auth/login", { method: "POST", body: { email, password } });
    saveTokens(tokens);
    setUser(await api<User>("/auth/me"));
  }, []);

  const logout = useCallback(() => {
    saveTokens(null);
    setUser(null);
  }, []);

  return <AuthContext.Provider value={{ user, loading, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth în afara AuthProvider");
  return ctx;
}
