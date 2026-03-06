"use client";

import { useCallback, useRef, useState } from "react";
import { mockStream } from "@/lib/mockStream";
import type { AiMessage, ChatMessage, StreamEvent, TaskItem, ToolCall } from "@/lib/types";

const createId = () => Math.random().toString(36).slice(2);

const emptyAiMessage = (): AiMessage => ({
  id: createId(),
  role: "assistant",
  content: "",
  thinking: [],
  toolCalls: [],
  tasks: [],
  status: "thinking",
});

export function useChatStream() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [threadId, setThreadId] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const stopRef = useRef(false);
  const activeMessageIdRef = useRef<string | null>(null);
  const threadIdRef = useRef<string | null>(null);

  const stop = useCallback(() => {
    controllerRef.current?.abort();
    stopRef.current = true;
    setIsStreaming(false);
  }, []);

  const applyEvent = useCallback((event: StreamEvent) => {
    setMessages((prev) => {
      if (event.type === "end") {
        return prev;
      }

      const next = [...prev];
      const activeId = activeMessageIdRef.current;
      let lastAi = (activeId
        ? next.find((msg) => msg.role === "assistant" && msg.id === activeId)
        : next.slice().reverse().find((msg) => msg.role === "assistant")) as AiMessage | undefined;

      if (!lastAi) {
        lastAi = emptyAiMessage();
        next.push(lastAi);
        activeMessageIdRef.current = lastAi.id;
      }

      if (event.type === "log") {
        const lastStep = lastAi.thinking[lastAi.thinking.length - 1];
        if (lastStep !== event.message) {
          lastAi.thinking = [...lastAi.thinking, event.message];
        }
        if (lastAi.status !== "streaming") {
          lastAi.status = "thinking";
        }
      }

      if (event.type === "start") {
        if (event.thread_id) {
          threadIdRef.current = event.thread_id;
          setThreadId(event.thread_id);
        }
      }

      // 模型思考 token（打字机追加到 thinking）
      if (event.type === "thinking_token") {
        const last = lastAi.thinking[lastAi.thinking.length - 1];
        if (typeof last === "string" && !last.startsWith("🤔") && !last.startsWith("✓") && !last.startsWith("📋") && !last.startsWith("📊") && !last.startsWith("💬")) {
          // 追加到最后一个思考条目
          lastAi.thinking = [...lastAi.thinking.slice(0, -1), last + event.delta];
        } else {
          lastAi.thinking = [...lastAi.thinking, event.delta];
        }
        lastAi.status = "streaming";
      }

      // 最终回答 token（打字机追加到 content）
      if (event.type === "content_token") {
        lastAi.content = (lastAi.content || "") + event.delta;
        lastAi.status = "streaming";
      }

      if (event.type === "task_start") {
        const exists = lastAi.tasks.some((task) => task.id === event.task_id);
        if (exists) {
          return [...next];
        }
        const task: TaskItem = {
          id: event.task_id,
          label: event.description,
          status: "pending",
        };
        lastAi.tasks = [...lastAi.tasks, task];
      }

      if (event.type === "task_running") {
        let updated = false;
        lastAi.tasks = lastAi.tasks.map((task) => {
          if (!updated && task.id === event.task_id) {
            updated = true;
            return { ...task, status: "running" };
          }
          return task;
        });
      }

      if (event.type === "task_complete") {
        let updated = false;
        lastAi.tasks = lastAi.tasks.map((task) => {
          if (!updated && task.id === event.task_id) {
            updated = true;
            return { ...task, status: "completed" };
          }
          return task;
        });
      }

      if (event.type === "tool_call") {
        const signature = `${event.tool_name}|${event.arguments || "{}"}`;
        const exists = lastAi.toolCalls.some(
          (tool) => `${tool.name}|${tool.input}` === signature
        );
        if (exists) {
          return [...next];
        }
        const toolCall: ToolCall = {
          id: createId(),
          name: event.tool_name,
          input: event.arguments || "{}",
          status: "running",
        };
        lastAi.toolCalls = [...lastAi.toolCalls, toolCall];
      }

      if (event.type === "tool_result") {
        let updated = false;
        lastAi.toolCalls = lastAi.toolCalls.map((tool) => {
          if (!updated && tool.name === event.tool_name && tool.status === "running") {
            updated = true;
            return { ...tool, status: "completed", output: event.result };
          }
          return tool;
        });
      }

      if (event.type === "final") {
        // 如果已经通过 content_token 流式生成了内容，绝不覆盖（避免重复）
        // 只有在内容为空时（比如极速回复或流式失败）才应用 final 的 reply
        if (!lastAi.content || lastAi.content.length === 0) {
          lastAi.content = event.reply;
        }
        lastAi.status = "done";
        activeMessageIdRef.current = null;
      }

      if (event.type === "error") {
        lastAi.status = "error";
        activeMessageIdRef.current = null;
      }

      return [...next];
    });
  }, []);

  const sendMessage = useCallback(async (query: string) => {
    setError(null);
    setIsStreaming(true);
    stopRef.current = false;

    setMessages((prev) => [
      ...prev,
      { id: createId(), role: "user", content: query },
      (() => {
        const message = emptyAiMessage();
        activeMessageIdRef.current = message.id;
        return message;
      })(),
    ]);

    try {
      const useMock = process.env.NEXT_PUBLIC_USE_MOCK === "true";

      if (useMock) {
        for await (const event of mockStream(query)) {
          if (stopRef.current) break;
          applyEvent(event);
        }
      } else {
        const backendBase = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
        const streamUrl = `${backendBase.replace(/\/$/, "")}/chat/stream`;
        controllerRef.current = new AbortController();
        const payload: { query: string; thread_id?: string } = { query };
        if (threadIdRef.current) {
          payload.thread_id = threadIdRef.current;
        }
        const response = await fetch(streamUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: controllerRef.current.signal,
        });

        if (!response.body) {
          throw new Error("流式响应不可用");
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          if (stopRef.current) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed.startsWith("data: ")) continue;
            const payload = trimmed.slice(6);
            if (!payload) continue;
            const event = JSON.parse(payload) as StreamEvent;
            applyEvent(event);
          }
        }
      }
      setIsStreaming(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "流式请求失败");
      setIsStreaming(false);
    }
  }, [applyEvent]);

  const loadConversation = useCallback((nextMessages: ChatMessage[], nextThreadId?: string | null) => {
    controllerRef.current?.abort();
    stopRef.current = false;
    activeMessageIdRef.current = null;
    threadIdRef.current = nextThreadId ?? null;
    setThreadId(nextThreadId ?? null);
    setError(null);
    setIsStreaming(false);
    setMessages(nextMessages);
  }, []);

  const resetConversation = useCallback(() => {
    controllerRef.current?.abort();
    stopRef.current = false;
    activeMessageIdRef.current = null;
    threadIdRef.current = null;
    setThreadId(null);
    setError(null);
    setIsStreaming(false);
    setMessages([]);
  }, []);

  return { messages, isStreaming, error, sendMessage, stop, loadConversation, resetConversation, threadId };
}
