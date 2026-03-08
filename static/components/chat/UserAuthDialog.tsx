"use client";

import { useState } from "react";
import { User, LogOut, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import type { AuthUser } from "@/lib/types";

type Tab = "login" | "register";

type UserAuthDialogProps = {
  user: AuthUser | null;
  onLogin: (username: string, password: string) => Promise<AuthUser>;
  onRegister: (username: string, password: string) => Promise<AuthUser>;
  onLogout: () => void;
};

export function UserAuthDialog({ user, onLogin, onRegister, onLogout }: UserAuthDialogProps) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);

  const resetForm = () => {
    setUsername("");
    setPassword("");
    setError(null);
    setLoading(false);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) {
      setError("请填写用户名和密码");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      if (tab === "login") {
        await onLogin(username.trim(), password);
      } else {
        await onRegister(username.trim(), password);
      }
      resetForm();
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败，请重试");
    } finally {
      setLoading(false);
    }
  };

  // ─── Logged-in state: show username button with logout ───────────────────
  if (user) {
    return (
      <div className="fixed bottom-5 right-5 z-50">
        <div className="relative">
          <Button
            variant="outline"
            size="sm"
            className="gap-2 rounded-full border-border/70 bg-background/90 shadow-md backdrop-blur"
            onClick={() => setUserMenuOpen((v) => !v)}
          >
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/20 text-xs font-bold text-primary">
              {user.username[0]?.toUpperCase()}
            </span>
            <span className="max-w-[100px] truncate text-xs font-medium">{user.username}</span>
            <ChevronDown className="h-3 w-3 text-muted-foreground" />
          </Button>

          {userMenuOpen && (
            <>
              {/* Backdrop */}
              <div
                className="fixed inset-0 z-40"
                onClick={() => setUserMenuOpen(false)}
              />
              <div className="absolute bottom-10 right-0 z-50 min-w-[160px] rounded-2xl border border-border/60 bg-background/95 p-1 shadow-xl backdrop-blur">
                <div className="px-3 py-2 text-xs text-muted-foreground">
                  已登录为 <span className="font-semibold text-foreground">{user.username}</span>
                </div>
                <div className="my-1 h-px bg-border/50" />
                <button
                  type="button"
                  className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-rose-600 hover:bg-rose-500/10"
                  onClick={() => {
                    setUserMenuOpen(false);
                    onLogout();
                  }}
                >
                  <LogOut className="h-3.5 w-3.5" />
                  退出登录
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    );
  }

  // ─── Logged-out state: show login/register button ────────────────────────
  return (
    <div className="fixed bottom-5 right-5 z-50">
      <Button
        variant="outline"
        size="sm"
        className="gap-2 rounded-full border-border/70 bg-background/90 shadow-md backdrop-blur"
        onClick={() => {
          resetForm();
          setOpen(true);
        }}
      >
        <User className="h-4 w-4" />
        登录 / 注册
      </Button>

      {open && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40 bg-black/40"
            onClick={() => {
              resetForm();
              setOpen(false);
            }}
          />

          {/* Dialog */}
          <div className="fixed bottom-16 right-5 z-50 w-80">
            <Card className="border-border/70 bg-background/98 shadow-2xl backdrop-blur">
              <CardHeader className="pb-3">
                <CardTitle className="text-base">账号</CardTitle>
                <CardDescription className="text-xs">
                  登录后可同步历史对话到云端
                </CardDescription>
              </CardHeader>
              <CardContent>
                {/* Tabs */}
                <div className="mb-4 flex gap-1 rounded-xl bg-muted/60 p-1">
                  {(["login", "register"] as Tab[]).map((t) => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => {
                        setTab(t);
                        setError(null);
                      }}
                      className={[
                        "flex-1 rounded-lg py-1.5 text-xs font-medium transition-colors",
                        tab === t
                          ? "bg-background text-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground",
                      ].join(" ")}
                    >
                      {t === "login" ? "登录" : "注册"}
                    </button>
                  ))}
                </div>

                <form onSubmit={handleSubmit} className="space-y-3">
                  <Input
                    placeholder="用户名"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    autoComplete="username"
                    disabled={loading}
                  />
                  <Input
                    type="password"
                    placeholder="密码（至少6位）"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete={tab === "login" ? "current-password" : "new-password"}
                    disabled={loading}
                  />

                  {error && (
                    <p className="rounded-lg bg-rose-500/10 px-3 py-2 text-xs text-rose-600">
                      {error}
                    </p>
                  )}

                  <Button type="submit" className="w-full" size="sm" disabled={loading}>
                    {loading ? "处理中..." : tab === "login" ? "登录" : "创建账号"}
                  </Button>
                </form>
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
