export type ToolCall = {
  id: string;
  name: string;
  input: string;
  output?: string;
  status: "pending" | "running" | "completed" | "error";
};

export type TaskItem = {
  id: string;
  label: string;
  status: "pending" | "running" | "completed" | "error";
};

export type AiMessage = {
  id: string;
  role: "assistant";
  content: string;
  thinking: string[];
  toolCalls: ToolCall[];
  tasks: TaskItem[];
  status: "thinking" | "streaming" | "done" | "error";
};

export type UserMessage = {
  id: string;
  role: "user";
  content: string;
};

export type ChatMessage = AiMessage | UserMessage;

export type ChatSession = {
  id: string;
  title: string;
  messages: ChatMessage[];
  threadId?: string | null;
  updatedAt: number;
};

export type StreamEvent =
  | { type: "start"; query: string; thread_id?: string }
  | { type: "log"; message: string; level?: "info" | "success" | "warning" | "error" }
  | { type: "task_start"; task_id: string; description: string }
  | { type: "task_running"; task_id: string }
  | { type: "tool_call"; tool_name: string; arguments?: string }
  | { type: "tool_result"; tool_name: string; result: string }
  | { type: "task_complete"; task_id: string }
  | { type: "task_failed"; task_id: string; error: string }
  | { type: "hitl_request"; task_id: string; tool_name: string; arguments: string; description: string }
  | { type: "thinking_token"; delta: string }
  | { type: "content_token"; delta: string }
  | { type: "final"; reply: string }
  | { type: "error"; message: string }
  | { type: "end" };

export type HitlRequest = {
  threadId: string;
  taskId: string;
  toolName: string;
  arguments: string;
  description: string;
};

// ─── Auth & User ─────────────────────────────────────────────────────────────

export type AuthUser = {
  user_id: string;
  username: string;
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
  user_id: string;
  username: string;
};

// ─── Backend Thread / Message ─────────────────────────────────────────────────

export type BackendThread = {
  id: string;
  title: string;
  updated_at: string;
  created_at: string;
};

export type BackendMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  meta: Record<string, unknown> | null;
  created_at: string;
};
