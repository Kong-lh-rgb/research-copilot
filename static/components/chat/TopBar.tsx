"use client";

import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

type TopBarProps = {
  onNewConversation: () => void;
};

export function TopBar({ onNewConversation }: TopBarProps) {
  return (
    <div className="flex items-center justify-between border-b border-border/60 bg-background/70 px-5 py-4 backdrop-blur">
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <span className="text-base">◎</span>
        </div>
        <div>
          <p className="text-sm font-semibold text-foreground">深度研究助手</p>
          <p className="text-xs text-muted-foreground">多步骤推理与工具调用助手</p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <Button variant="outline" size="sm" className="gap-2" onClick={onNewConversation}>
          <Plus className="h-4 w-4" />
          新建对话
        </Button>
      </div>
    </div>
  );
}
