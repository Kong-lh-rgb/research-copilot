"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchMe, getStoredUser, getToken, login, register, removeToken, setToken } from "@/lib/api";
import type { AuthUser } from "@/lib/types";

export type AuthState = {
  user: AuthUser | null;
  loading: boolean;
};

export function useAuth() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  // On mount: restore session from localStorage and verify token
  useEffect(() => {
    const stored = getStoredUser();
    const token = getToken();

    if (!token || !stored) {
      setLoading(false);
      return;
    }

    // Optimistically restore from localStorage, then verify with server
    setUser(stored);
    fetchMe()
      .then((me) => setUser(me))
      .catch(() => {
        removeToken();
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const handleLogin = useCallback(async (username: string, password: string) => {
    const res = await login(username, password);
    const authUser: AuthUser = { user_id: res.user_id, username: res.username };
    setToken(res.access_token, authUser);
    setUser(authUser);
    return authUser;
  }, []);

  const handleRegister = useCallback(async (username: string, password: string) => {
    const res = await register(username, password);
    const authUser: AuthUser = { user_id: res.user_id, username: res.username };
    setToken(res.access_token, authUser);
    setUser(authUser);
    return authUser;
  }, []);

  const handleLogout = useCallback(() => {
    removeToken();
    setUser(null);
  }, []);

  return { user, loading, login: handleLogin, register: handleRegister, logout: handleLogout };
}
