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
  | { type: "final"; reply: string }
  | { type: "error"; message: string }
  | { type: "end" };
