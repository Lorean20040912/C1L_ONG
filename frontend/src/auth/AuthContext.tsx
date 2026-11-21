import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, hasTokens, saveTokens, type TokenPair } from "../api/client";
import type { User } from "../api/types";

interface AuthState {
  user: User | null;
  loading: boolean;
  /** întoarce jetonul de provocare dacă contul cere al doilea factor (2FA), altfel None */
  login: (email: string, password: string) => Promise<string | null>;
  login2fa: (challengeToken: string, code: string) => Promise<void>;
  logout: () => void;
}

interface LoginResponse extends Partial<TokenPair> {
  requires_2fa: boolean;
  challenge_token: string | null;
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
    const res = await api<LoginResponse>("/auth/login", { method: "POST", body: { email, password } });
    if (res.requires_2fa && res.challenge_token) return res.challenge_token;
    saveTokens(res as TokenPair);
    setUser(await api<User>("/auth/me"));
    return null;
  }, []);

  const login2fa = useCallback(async (challenge_token: string, code: string) => {
    const tokens = await api<TokenPair>("/auth/login/2fa", { method: "POST", body: { challenge_token, code } });
    saveTokens(tokens);
    setUser(await api<User>("/auth/me"));
  }, []);

  const logout = useCallback(() => {
    saveTokens(null);
    setUser(null);
  }, []);

  return <AuthContext.Provider value={{ user, loading, login, login2fa, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth în afara AuthProvider");
  return ctx;
}
