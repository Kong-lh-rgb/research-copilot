import type { AuthUser, BackendMessage, BackendThread, TokenResponse } from "@/lib/types";

const TOKEN_KEY = "deep-researcher-auth-token";
const USER_KEY = "deep-researcher-auth-user";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string, user: AuthUser): void {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function removeToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

export function getStoredUser(): AuthUser | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

// ─── Base fetch helper ────────────────────────────────────────────────────────

const backendBase = (): string =>
  (process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");

async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  withAuth = false,
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  if (withAuth) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${backendBase()}${path}`, { ...options, headers });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const json = await res.json();
      detail = json.detail ?? detail;
    } catch {
      // ignore
    }
    throw new Error(detail);
  }

  // 204 No Content
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ─── Auth API ─────────────────────────────────────────────────────────────────

export async function register(
  username: string,
  password: string,
): Promise<TokenResponse> {
  return apiFetch<TokenResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function login(
  username: string,
  password: string,
): Promise<TokenResponse> {
  return apiFetch<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function fetchMe(): Promise<AuthUser> {
  return apiFetch<AuthUser>("/auth/me", {}, true);
}

// ─── Thread API ───────────────────────────────────────────────────────────────

export async function fetchThreads(): Promise<BackendThread[]> {
  return apiFetch<BackendThread[]>("/threads", {}, true);
}

export async function fetchThreadMessages(
  threadId: string,
): Promise<BackendMessage[]> {
  return apiFetch<BackendMessage[]>(`/threads/${threadId}/messages`, {}, true);
}

export async function deleteThread(threadId: string): Promise<void> {
  return apiFetch<void>(`/threads/${threadId}`, { method: "DELETE" }, true);
}
