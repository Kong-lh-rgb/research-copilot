"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Settings2, Square, RotateCcw, Send } from "lucide-react";

type ChatInputProps = {
  onSend: (value: string) => void;
  onStop: () => void;
  onRegenerate: () => void;
  onOpenSettings: () => void;
  isStreaming: boolean;
};

export function ChatInput({ onSend, onStop, onRegenerate, onOpenSettings, isStreaming }: ChatInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = Math.min(el.scrollHeight, 140) + "px";
  }, [value]);

  const handleSend = () => {
    const trimmed = value.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setValue("");
  };

  return (
    <div className="border-t border-border/60 bg-background/80 px-5 py-4 backdrop-blur">
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-3">
        <Textarea
          ref={textareaRef}
          placeholder="问我任何问题，或者让我执行任务…"
          className="min-h-[54px] resize-none rounded-2xl border-border/60 bg-muted/40 px-4 py-3 text-sm shadow-sm focus-visible:ring-1"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              handleSend();
            }
          }}
        />
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className="gap-2"
              onClick={onOpenSettings}
            >
              <Settings2 className="h-4 w-4" />
              设置
            </Button>
            {isStreaming ? (
              <Button variant="outline" size="sm" className="gap-2" onClick={onStop}>
                <Square className="h-4 w-4" />
                停止生成
              </Button>
            ) : (
              <Button variant="outline" size="sm" className="gap-2" onClick={onRegenerate}>
                <RotateCcw className="h-4 w-4" />
                重新生成
              </Button>
            )}
          </div>
          <Button onClick={handleSend} className="gap-2">
            <Send className="h-4 w-4" />
            发送
          </Button>
        </div>
      </div>
    </div>
  );
}
