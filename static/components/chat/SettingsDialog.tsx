"use client";

import { useEffect, useState } from "react";
import { X, Sun, Moon, Monitor, KeyRound, Check } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { getAccessCode, setAccessCode } from "@/lib/api";

type SettingsDialogProps = {
  open: boolean;
  onClose: () => void;
};

export function SettingsDialog({ open, onClose }: SettingsDialogProps) {
  const { theme, setTheme } = useTheme();
  const [code, setCode] = useState("");
  const [saved, setSaved] = useState(false);

  // Load stored code when dialog opens
  useEffect(() => {
    if (open) setCode(getAccessCode());
  }, [open]);

  const handleSave = () => {
    setAccessCode(code.trim());
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 px-4" onClick={onClose}>
      <Card
        className="w-full max-w-2xl gap-0 border-border/70 bg-background/95 py-0 shadow-2xl backdrop-blur"
        onClick={(event) => event.stopPropagation()}
      >
        <CardHeader className="border-b border-border/60 py-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <CardTitle className="text-lg">设置</CardTitle>
              <CardDescription className="mt-1">
                填写内部邀请码后才可发送请求。
              </CardDescription>
            </div>
            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          </div>
        </CardHeader>

        <CardContent className="space-y-6 py-6">
          {/* ── 邀请码 ─────────────────────────────────────────────────────── */}
          <section className="space-y-3">
            <div>
              <h3 className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
                <KeyRound className="h-4 w-4" />
                内部邀请码
              </h3>
              <p className="mt-1 text-xs text-muted-foreground">
                每次发送对话请求时会附在请求头中，服务端校验通过后才会调用模型。
              </p>
            </div>
            <div className="flex gap-2">
              <Input
                type="password"
                placeholder="请输入内部邀请码"
                value={code}
                onChange={(e) => { setCode(e.target.value); setSaved(false); }}
                onKeyDown={(e) => e.key === "Enter" && handleSave()}
                className="font-mono"
                autoComplete="off"
              />
              <Button size="sm" onClick={handleSave} className="shrink-0 gap-1.5">
                {saved ? <Check className="h-3.5 w-3.5" /> : null}
                {saved ? "已保存" : "保存"}
              </Button>
            </div>
          </section>

          {/* ── 外观主题 ──────────────────────────────────────────────────── */}
          <section className="space-y-4">
            <div>
              <h3 className="text-sm font-semibold text-foreground">外观主题</h3>
              <p className="mt-1 text-xs text-muted-foreground">选择界面的亮暗模式。</p>
            </div>
            <div className="flex gap-2">
              {(
                [
                  { value: "light", label: "浅色", icon: Sun },
                  { value: "dark", label: "深色", icon: Moon },
                  { value: "system", label: "跟随系统", icon: Monitor },
                ] as const
              ).map(({ value, label, icon: Icon }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setTheme(value)}
                  className={[
                    "flex flex-1 flex-col items-center gap-1.5 rounded-xl border py-3 text-xs font-medium transition-colors",
                    theme === value
                      ? "border-primary/50 bg-primary/10 text-primary"
                      : "border-border/60 bg-muted/30 text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                  ].join(" ")}
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </button>
              ))}
            </div>
          </section>
        </CardContent>
      </Card>
    </div>
  );
}
