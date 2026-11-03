"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, refreshAccessToken, setAccessToken, setSignedOutHandler, unwrap, type Schemas } from "./api";

export type Role = Schemas["UserRole"];
export type Me = Schemas["UserOut"];

type AuthState = {
  me: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

async function loadMe(): Promise<Me> {
  return unwrap(await api.GET("/v1/me"));
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  // On first load the access token is gone (it was only in memory); the httpOnly refresh
  // cookie, if still valid, gets a new one.
  useEffect(() => {
    setSignedOutHandler(() => {
      setMe(null);
      if (window.location.pathname !== "/login") window.location.assign("/login");
    });
    void (async () => {
      try {
        if (await refreshAccessToken()) setMe(await loadMe());
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const tokens = unwrap(await api.POST("/v1/auth/login", { body: { email, password } }));
    setAccessToken(tokens.access_token);
    setMe(await loadMe());
  }, []);

  const logout = useCallback(async () => {
    await api.POST("/v1/auth/logout");
    setAccessToken(null);
    setMe(null);
    window.location.assign("/login");
  }, []);

  const value = useMemo(() => ({ me, loading, login, logout }), [me, loading, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

export function isOfficer(role: Role | undefined): boolean {
  return role === "officer" || role === "admin";
}
