"use client";

import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { HitlRequest } from "@/lib/types";

type Props = {
  request: HitlRequest;
  onConfirm: (approved: boolean) => void;
};

function prettyArgs(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

const TOOL_LABELS: Record<string, string> = {
  send_email: "发送邮件",
  send_wechat: "发送微信",
  send_sms: "发送短信",
  create_order: "创建订单",
  transfer_money: "资金转账",
};

export function HitlConfirmCard({ request, onConfirm }: Props) {
  const label = TOOL_LABELS[request.toolName] ?? request.toolName;
  const args = prettyArgs(request.arguments);

  return (
    <div className="mx-auto mb-3 w-full max-w-2xl rounded-xl border border-amber-500/40 bg-amber-500/5 p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-500" />
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-foreground">需要您确认</span>
            <Badge variant="outline" className="border-amber-500/50 text-amber-600 dark:text-amber-400">
              {label}
            </Badge>
          </div>

          <p className="text-xs text-muted-foreground">{request.description}</p>

          {args && args !== "{}" && (
            <pre className="overflow-x-auto rounded-lg bg-muted/50 p-2 text-xs text-muted-foreground">
              {args}
            </pre>
          )}

          <div className="flex gap-2 pt-1">
            <Button
              size="sm"
              onClick={() => onConfirm(true)}
              className="bg-emerald-600 text-white hover:bg-emerald-700"
            >
              确认执行
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => onConfirm(false)}
              className="border-destructive/60 text-destructive hover:bg-destructive/10"
            >
              取消
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
