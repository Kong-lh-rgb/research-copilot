"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { ChatInput } from "@/components/chat/ChatInput";
import { ChatSidebar } from "@/components/chat/ChatSidebar";
import { SettingsDialog } from "@/components/chat/SettingsDialog";
import { TopBar } from "@/components/chat/TopBar";
import { UserAuthDialog } from "@/components/chat/UserAuthDialog";
import { HitlConfirmCard } from "@/components/chat/HitlConfirmCard";
import { useChatStream } from "@/hooks/useChatStream";
import { useAuth } from "@/hooks/useAuth";
import { deleteThread, fetchThreadMessages, fetchThreads } from "@/lib/api";
import type { AiMessage, ChatMessage as ChatMessageType, ChatSession } from "@/lib/types";

const STORAGE_KEY = "deep-research-chat-sessions";
const createId = () => Math.random().toString(36).slice(2);

function createEmptySession(): ChatSession {
  return { id: createId(), title: "新对话", messages: [], threadId: null, updatedAt: Date.now() };
}

function createSessionWithThread(threadId: string): ChatSession {
  return { id: threadId, title: "新对话", messages: [], threadId, updatedAt: Date.now() };
}

function getSessionTitle(messages: ChatMessageType[]) {
  const first = messages.find((m) => m.role === "user");
  return first?.content?.slice(0, 18) || "新对话";
}

type BackendMsg = Awaited<ReturnType<typeof fetchThreadMessages>>[number];

function backendMsgsToChat(msgs: BackendMsg[]): ChatMessageType[] {
  return msgs.map((m): ChatMessageType => {
    if (m.role === "user") return { id: createId(), role: "user", content: m.content };
    return {
      id: createId(),
      role: "assistant",
      content: m.content,
      thinking: [],
      toolCalls: [],
      tasks: [],
      status: "done",
    } satisfies AiMessage;
  });
}

export function ChatContainer() {
  const auth = useAuth();
  const { messages, isStreaming, error, sendMessage, stop, loadConversation, resetConversation, threadId, hitlRequest, confirmHitl } =
    useChatStream();

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const userScrolledUpRef = useRef(false);   // true when user manually scrolled up
  const wasStreamingRef = useRef(false);      // track streaming edge

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const hydratedRef = useRef(false);
  const prevStreamingRef = useRef(false);

  // ─── Smart auto-scroll ────────────────────────────────────────────────────
  // When streaming kicks off, snap to bottom and clear the "user scrolled up" flag.
  useEffect(() => {
    if (isStreaming && !wasStreamingRef.current) {
      userScrolledUpRef.current = false;
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
    }
    wasStreamingRef.current = isStreaming;
  }, [isStreaming]);

  // Follow new messages only when the user hasn't scrolled away.
  useEffect(() => {
    if (userScrolledUpRef.current) return;
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    // If user is within 80px of the bottom, consider them "at the bottom"
    userScrolledUpRef.current = el.scrollHeight - el.scrollTop - el.clientHeight > 80;
  }, []);

  // ─── Bootstrap: load sessions based on auth state ─────────────────────────
  useEffect(() => {
    if (auth.loading) return;

    if (auth.user) {
      fetchThreads()
        .then(async (threads) => {
          if (threads.length === 0) {
            const s = createEmptySession();
            setSessions([s]);
            setActiveSessionId(s.id);
            resetConversation();
          } else {
            const mapped: ChatSession[] = threads.map((t) => ({
              id: t.id,
              title: t.title,
              messages: [],
              threadId: t.id,
              updatedAt: new Date(t.updated_at).getTime(),
            }));
            setSessions(mapped);
            setActiveSessionId(mapped[0].id);
            const msgs = await fetchThreadMessages(mapped[0].id).catch(() => []);
            loadConversation(backendMsgsToChat(msgs), mapped[0].id);
          }
        })
        .catch(() => {
          const s = createEmptySession();
          setSessions([s]);
          setActiveSessionId(s.id);
          resetConversation();
        });
    } else {
      try {
        const raw = window.localStorage.getItem(STORAGE_KEY);
        const parsed = raw ? (JSON.parse(raw) as ChatSession[]) : [];
        if (parsed.length > 0) {
          const sorted = parsed.sort((a, b) => b.updatedAt - a.updatedAt);
          setSessions(sorted);
          setActiveSessionId(sorted[0].id);
          loadConversation(sorted[0].messages, sorted[0].threadId ?? null);
        } else {
          const s = createEmptySession();
          setSessions([s]);
          setActiveSessionId(s.id);
          resetConversation();
        }
      } catch {
        const s = createEmptySession();
        setSessions([s]);
        setActiveSessionId(s.id);
        resetConversation();
      }
    }
    hydratedRef.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth.loading, auth.user]);

  // ─── Persist to localStorage when NOT logged in ────────────────────────────
  useEffect(() => {
    if (!hydratedRef.current || !activeSessionId || auth.user) return;
    setSessions((prev) => {
      const next = prev.map((s) =>
        s.id === activeSessionId
          ? { ...s, messages, threadId, updatedAt: Date.now(), title: getSessionTitle(messages) }
          : s
      );
      next.sort((a, b) => b.updatedAt - a.updatedAt);
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      return [...next];
    });
  }, [messages, activeSessionId, threadId, auth.user]);

  // ─── Refresh thread list after each streaming turn (logged in) ────────────
  useEffect(() => {
    const wasStreaming = prevStreamingRef.current;
    prevStreamingRef.current = isStreaming;
    if (!auth.user || !wasStreaming || isStreaming) return;

    fetchThreads()
      .then((threads) => {
        setSessions((prev) => {
          const mapped: ChatSession[] = threads.map((t) => {
            const existing = prev.find((s) => s.id === t.id);
            return {
              id: t.id,
              title: t.title,
              messages: existing?.messages ?? [],
              threadId: t.id,
              updatedAt: new Date(t.updated_at).getTime(),
            };
          });
          const backendIds = new Set(mapped.map((s) => s.id));
          const pending = prev.filter((s) => !backendIds.has(s.id));
          return [...mapped, ...pending].sort((a, b) => b.updatedAt - a.updatedAt);
        });
      })
      .catch(() => {});
  }, [isStreaming, auth.user]);

  const activeSession = useMemo(
    () => sessions.find((s) => s.id === activeSessionId) ?? null,
    [sessions, activeSessionId]
  );

  // ─── Select session ────────────────────────────────────────────────────────
  const handleSelectSession = useCallback(
    async (sessionId: string) => {
      if (sessionId === activeSessionId) return;
      const session = sessions.find((s) => s.id === sessionId);
      if (!session) return;
      setActiveSessionId(sessionId);
      if (auth.user && session.threadId) {
        const msgs = await fetchThreadMessages(session.threadId).catch(() => []);
        loadConversation(backendMsgsToChat(msgs), session.threadId);
      } else {
        loadConversation(session.messages, session.threadId ?? null);
      }
    },
    [activeSessionId, auth.user, loadConversation, sessions]
  );

  // ─── Delete session ────────────────────────────────────────────────────────
  const handleDeleteSession = useCallback(
    async (sessionId: string) => {
      if (auth.user) await deleteThread(sessionId).catch(() => {});
      setSessions((prev) => {
        const next = prev.filter((s) => s.id !== sessionId);
        if (!auth.user) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
        return next;
      });
      if (activeSessionId === sessionId) {
        const remaining = sessions.filter((s) => s.id !== sessionId);
        if (remaining.length > 0) {
          const first = remaining[0];
          setActiveSessionId(first.id);
          if (auth.user && first.threadId) {
            const msgs = await fetchThreadMessages(first.threadId).catch(() => []);
            loadConversation(backendMsgsToChat(msgs), first.threadId);
          } else {
            loadConversation(first.messages, first.threadId ?? null);
          }
        } else {
          handleCreateSession();
        }
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [activeSessionId, auth.user, sessions, loadConversation]
  );

  // ─── New conversation ──────────────────────────────────────────────────────
  const handleCreateSession = useCallback(() => {
    if (auth.user) {
      const newThreadId = `web_${createId()}`;
      const s = createSessionWithThread(newThreadId);
      setSessions((prev) => [s, ...prev]);
      setActiveSessionId(newThreadId);
      loadConversation([], newThreadId);
    } else {
      const s = createEmptySession();
      setSessions((prev) => {
        const next = [s, ...prev];
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
        return next;
      });
      setActiveSessionId(s.id);
      resetConversation();
    }
  }, [auth.user, loadConversation, resetConversation]);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-gradient-to-b from-background via-background to-muted/30">
      <TopBar />
      <main className="flex min-h-0 flex-1 overflow-hidden">
        <ChatSidebar
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelectSession={handleSelectSession}
          onCreateSession={handleCreateSession}
          onDeleteSession={auth.user ? handleDeleteSession : undefined}
        />
        {/* Right panel: messages + input, aligned together */}
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <div className="mx-auto flex min-h-0 w-full max-w-4xl flex-1 flex-col gap-6 overflow-hidden px-5 pt-6">
            <div
              ref={scrollRef}
              onScroll={handleScroll}
              className="scrollbar-elegant flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto rounded-3xl border border-border/60 bg-card/60 p-6 shadow-sm"
            >
              {messages.length === 0 ? (
                <div className="flex h-full flex-col items-center justify-center gap-4 text-center text-muted-foreground">
                  <p className="text-lg font-semibold text-foreground">欢迎使用深度研究助手</p>
                  <p className="max-w-md text-sm">
                    {activeSession
                      ? "当前会话已准备就绪。输入问题开始新的推理任务。"
                      : "选择左侧会话或新建对话开始使用。"}
                  </p>
                </div>
              ) : (
                messages.map((message) => <ChatMessage key={message.id} message={message} />)
              )}
              {error && (
                <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-2 text-sm text-rose-600">
                  {error}
                </div>
              )}
            </div>
          </div>
          {hitlRequest && (
            <HitlConfirmCard request={hitlRequest} onConfirm={confirmHitl} />
          )}
          <ChatInput
            onSend={sendMessage}
            onStop={stop}
            onRegenerate={() => {
              const lastUser = [...messages].reverse().find((msg) => msg.role === "user");
              if (lastUser) sendMessage(lastUser.content);
            }}
            onOpenSettings={() => setSettingsOpen(true)}
            isStreaming={isStreaming}
          />
        </div>
      </main>
      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />

      {/* User auth – fixed bottom-right */}
      <UserAuthDialog
        user={auth.user}
        onLogin={auth.login}
        onRegister={auth.register}
        onLogout={auth.logout}
      />
    </div>
  );
}
