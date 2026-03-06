"use client";

import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { TaskItem } from "@/lib/types";

const statusStyle: Record<TaskItem["status"], string> = {
  pending: "bg-muted text-muted-foreground",
  running: "bg-blue-500/10 text-blue-600",
  completed: "bg-emerald-500/10 text-emerald-600",
  error: "bg-rose-500/10 text-rose-600",
};

export function TaskProgressPanel({ tasks }: { tasks: TaskItem[] }) {
  if (!tasks.length) return null;

  return (
    <Card className="border-border/60 bg-background/80 p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold">任务执行</p>
        <span className="text-xs text-muted-foreground">{tasks.length} 项</span>
      </div>
      <ul className="mt-3 space-y-2 text-sm">
        {tasks.map((task) => (
          <li key={task.id} className="flex items-center justify-between">
            <span className="text-muted-foreground">{task.label}</span>
            <Badge className={statusStyle[task.status]}>{task.status}</Badge>
          </li>
        ))}
      </ul>
    </Card>
  );
}
