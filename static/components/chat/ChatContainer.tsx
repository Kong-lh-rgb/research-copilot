"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { ChatInput } from "@/components/chat/ChatInput";
import { ChatSidebar } from "@/components/chat/ChatSidebar";
import { SettingsDialog } from "@/components/chat/SettingsDialog";
import { TopBar } from "@/components/chat/TopBar";
import { useChatStream } from "@/hooks/useChatStream";
import type { ChatMessage as ChatMessageType, ChatSession } from "@/lib/types";

const STORAGE_KEY = "deep-research-chat-sessions";

const createSessionId = () => Math.random().toString(36).slice(2);

function createEmptySession(): ChatSession {
  return {
    id: createSessionId(),
    title: "新对话",
    messages: [],
    threadId: null,
    updatedAt: Date.now(),
  };
}

function getSessionTitle(messages: ChatMessageType[]) {
  const firstUserMessage = messages.find((message) => message.role === "user");
  if (!firstUserMessage?.content) return "新对话";
  return firstUserMessage.content.slice(0, 18) || "新对话";
}

export function ChatContainer() {
  const { messages, isStreaming, error, sendMessage, stop, loadConversation, resetConversation, threadId } = useChatStream();
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const hydratedRef = useRef(false);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages]);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      const parsed = raw ? (JSON.parse(raw) as ChatSession[]) : [];
      if (parsed.length > 0) {
        const sorted = parsed.sort((a, b) => b.updatedAt - a.updatedAt);
        setSessions(sorted);
        setActiveSessionId(sorted[0].id);
        loadConversation(sorted[0].messages, sorted[0].threadId ?? null);
      } else {
        const initial = createEmptySession();
        setSessions([initial]);
        setActiveSessionId(initial.id);
        resetConversation();
      }
    } catch {
      const initial = createEmptySession();
      setSessions([initial]);
      setActiveSessionId(initial.id);
      resetConversation();
    }
    hydratedRef.current = true;
  }, [loadConversation, resetConversation]);

  useEffect(() => {
    if (!hydratedRef.current || !activeSessionId) return;
    setSessions((prev) => {
      const next = prev.map((session) =>
        session.id === activeSessionId
          ? {
              ...session,
              messages,
              threadId,
              updatedAt: Date.now(),
              title: getSessionTitle(messages),
            }
          : session
      );
      next.sort((a, b) => b.updatedAt - a.updatedAt);
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      return [...next];
    });
  }, [messages, activeSessionId, threadId]);

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === activeSessionId) ?? null,
    [sessions, activeSessionId]
  );

  const handleSelectSession = (sessionId: string) => {
    if (sessionId === activeSessionId) return;
    const session = sessions.find((item) => item.id === sessionId);
    if (!session) return;
    setActiveSessionId(sessionId);
    loadConversation(session.messages, session.threadId ?? null);
  };

  const handleCreateSession = () => {
    const nextSession = createEmptySession();
    setSessions((prev) => {
      const next = [nextSession, ...prev];
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      return next;
    });
    setActiveSessionId(nextSession.id);
    resetConversation();
  };

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-gradient-to-b from-background via-background to-muted/30">
      <TopBar onNewConversation={handleCreateSession} />
      <main className="flex min-h-0 flex-1 overflow-hidden">
        <ChatSidebar
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelectSession={handleSelectSession}
          onCreateSession={handleCreateSession}
        />
        <div className="mx-auto flex h-full min-h-0 w-full max-w-4xl flex-col gap-6 px-5 py-6">
          <div
            ref={scrollRef}
            className="scrollbar-elegant flex h-full min-h-0 flex-col gap-6 overflow-y-auto rounded-3xl border border-border/60 bg-card/60 p-6 shadow-sm"
          >
            {messages.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center gap-4 text-center text-muted-foreground">
                <p className="text-lg font-semibold text-foreground">欢迎使用深度研究助手</p>
                <p className="max-w-md text-sm">
                  {activeSession ? "当前会话已准备就绪。输入问题开始新的推理任务。" : "选择左侧会话或新建对话开始使用。"}
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
      </main>
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
      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
