"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { Copy, AlertCircle, StopCircle } from "lucide-react";
import type { AiMessage } from "@/lib/types";
import { ThinkingPanel } from "@/components/chat/ThinkingPanel";
import { ToolCallCard } from "@/components/chat/ToolCallCard";
import { TaskProgressPanel } from "@/components/chat/TaskProgressPanel";
import { StreamingText } from "@/components/chat/StreamingText";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";

export function AIMessage({ message }: { message: AiMessage }) {
  const [manualThinkingOpen, setManualThinkingOpen] = useState<boolean | null>(null);
  const [toolsOpen, setToolsOpen] = useState(false);

  const thinkingOpen = message.status === "done"
    ? manualThinkingOpen ?? false
    : manualThinkingOpen ?? true;

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="space-y-4">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-muted text-muted-foreground">AI</div>
        <div className="flex-1 space-y-3">
          <div className="rounded-2xl rounded-tl-sm border border-border/60 bg-card/80 px-4 py-3 shadow-sm">
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1">
                  {message.status === "error" ? (
                    <div className="flex items-start gap-2 text-sm text-destructive">
                      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                      <span>{message.content || "请求失败，请检查邀请码或總试。"}</span>
                    </div>
                  ) : message.status === "thinking" && !message.content ? (
                    <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
                      <span className="flex gap-0.5">
                        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:0ms]" />
                        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:150ms]" />
                        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:300ms]" />
                      </span>
                      AI 正在思考…
                    </span>
                  ) : message.status === "done" && !message.content ? (
                    <span className="flex items-center gap-1.5 text-sm text-muted-foreground/60">
                      <StopCircle className="h-3.5 w-3.5" />
                      已停止
                    </span>
                  ) : (
                    <StreamingText
                      text={message.content}
                      isStreaming={message.status === "streaming"}
                    />
                  )}
              </div>
              {message.content && message.status === "done" && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 shrink-0"
                  onClick={() => navigator.clipboard.writeText(message.content)}
                  aria-label="复制回答"
                >
                  <Copy className="h-3.5 w-3.5" />
                </Button>
              )}
            </div>
          </div>
          <ThinkingPanel steps={message.thinking} collapsed={!thinkingOpen} onToggle={(open) => setManualThinkingOpen(open)} />
          <TaskProgressPanel tasks={message.tasks} />
          {message.toolCalls.length > 0 && (
            <Accordion
              type="single"
              collapsible
              value={toolsOpen ? "tools" : ""}
              onValueChange={(value) => setToolsOpen(value === "tools")}
            >
              <AccordionItem value="tools" className="border-none">
                <AccordionTrigger className="py-2 text-xs font-semibold uppercase text-muted-foreground hover:no-underline">
                  工具调用记录
                </AccordionTrigger>
                <AccordionContent>
                  <div className="space-y-3">
                    {message.toolCalls.map((tool) => (
                      <ToolCallCard key={tool.id} tool={tool} />
                    ))}
                  </div>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          )}
        </div>
      </div>
    </motion.div>
  );
}
