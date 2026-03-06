"use client";

import { motion } from "framer-motion";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Wrench } from "lucide-react";
import type { ToolCall } from "@/lib/types";

const statusColor: Record<ToolCall["status"], string> = {
  pending: "bg-muted text-muted-foreground",
  running: "bg-blue-500/10 text-blue-600",
  completed: "bg-emerald-500/10 text-emerald-600",
  error: "bg-rose-500/10 text-rose-600",
};

export function ToolCallCard({ tool }: { tool: ToolCall }) {
  return (
    <motion.div layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="w-full">
      <Card className="border-border/60 bg-background/80 p-3 shadow-sm">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm font-medium">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Wrench className="h-4 w-4" />
            </span>
            正在调用工具：{tool.name}
          </div>
          <Badge className={statusColor[tool.status]}>{tool.status}</Badge>
        </div>
      </Card>
    </motion.div>
  );
}
