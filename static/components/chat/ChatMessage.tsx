"use client";

import type { ChatMessage as ChatMessageType } from "@/lib/types";
import { UserMessage } from "@/components/chat/UserMessage";
import { AIMessage } from "@/components/chat/AIMessage";

export function ChatMessage({ message }: { message: ChatMessageType }) {
  if (message.role === "user") {
    return <UserMessage message={message} />;
  }

  return <AIMessage message={message} />;
}
