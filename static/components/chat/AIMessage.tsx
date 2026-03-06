"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { Button } from "@/components/ui/button";
import { Copy } from "lucide-react";
import type { AiMessage } from "@/lib/types";
import { ThinkingPanel } from "@/components/chat/ThinkingPanel";
import { ToolCallCard } from "@/components/chat/ToolCallCard";
import { TaskProgressPanel } from "@/components/chat/TaskProgressPanel";
import { StreamingText } from "@/components/chat/StreamingText";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";

export function AIMessage({ message }: { message: AiMessage }) {
  const [manualThinkingOpen, setManualThinkingOpen] = useState<boolean | null>(null);
  const [toolsOpen, setToolsOpen] = useState(false);

  const content = useMemo(() => message.content, [message.content]);

  const thinkingOpen = message.status === "done"
    ? manualThinkingOpen ?? false
    : manualThinkingOpen ?? true;

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="space-y-4">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-muted text-muted-foreground">AI</div>
        <div className="flex-1 space-y-3">
          <div className="rounded-2xl rounded-tl-sm border border-border/60 bg-card/80 px-4 py-3 shadow-sm">
            {message.status === "streaming" ? (
              <StreamingText text={content || "AI 正在思考..."} isStreaming />
            ) : (
              <div className="flex items-start justify-between gap-3">
                <div className="prose prose-sm max-w-none flex-1 dark:prose-invert">
                  <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                    {content || "AI 正在思考..."}
                  </ReactMarkdown>
                </div>
                {content && message.status === "done" && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 shrink-0"
                    onClick={() => navigator.clipboard.writeText(content)}
                    aria-label="复制回答"
                  >
                    <Copy className="h-3.5 w-3.5" />
                  </Button>
                )}
              </div>
            )}
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
