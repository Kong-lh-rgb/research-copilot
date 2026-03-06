"use client";

import { MessageSquarePlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ChatSession } from "@/lib/types";

type ChatSidebarProps = {
  sessions: ChatSession[];
  activeSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onCreateSession: () => void;
};

function formatTime(timestamp: number) {
  return new Date(timestamp).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function ChatSidebar({ sessions, activeSessionId, onSelectSession, onCreateSession }: ChatSidebarProps) {
  return (
    <aside className="hidden h-full w-72 shrink-0 border-r border-border/60 bg-background/80 lg:flex lg:flex-col">
      <div className="border-b border-border/60 p-4">
        <Button className="w-full justify-start gap-2" onClick={onCreateSession}>
          <MessageSquarePlus className="h-4 w-4" />
          新建对话
        </Button>
      </div>
      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {sessions.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border/60 p-4 text-sm text-muted-foreground">
            暂无历史对话
          </div>
        ) : (
          sessions.map((session) => {
            const preview = session.messages.find((message) => message.role === "user")?.content ?? "空白对话";
            const isActive = session.id === activeSessionId;
            return (
              <button
                key={session.id}
                type="button"
                onClick={() => onSelectSession(session.id)}
                className={[
                  "w-full rounded-2xl border px-3 py-3 text-left transition-colors",
                  isActive
                    ? "border-primary/40 bg-primary/10"
                    : "border-border/50 bg-card/50 hover:bg-muted/60",
                ].join(" ")}
              >
                <div className="truncate text-sm font-medium text-foreground">{session.title}</div>
                <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">{preview}</div>
                <div className="mt-2 text-[11px] text-muted-foreground">{formatTime(session.updatedAt)}</div>
              </button>
            );
          })
        )}
      </div>
    </aside>
  );
}
