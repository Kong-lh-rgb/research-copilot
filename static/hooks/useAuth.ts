"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchMe, getStoredUser, getToken, login, register, removeToken, setToken } from "@/lib/api";
import type { AuthUser } from "@/lib/types";

export type AuthState = {
  user: AuthUser | null;
  loading: boolean;
};

export function useAuth() {
  const bootstrap = useMemo(() => {
    if (typeof window === "undefined") {
      return { token: null as string | null, user: null as AuthUser | null };
    }
    return { token: getToken(), user: getStoredUser() };
  }, []);

  const [user, setUser] = useState<AuthUser | null>(bootstrap.user);
  const [loading, setLoading] = useState(Boolean(bootstrap.token && bootstrap.user));

  // On mount: restore session from localStorage and verify token
  useEffect(() => {
    if (!bootstrap.token || !bootstrap.user) {
      return;
    }

    fetchMe()
      .then((me) => setUser(me))
      .catch(() => {
        removeToken();
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, [bootstrap.token, bootstrap.user]);

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
