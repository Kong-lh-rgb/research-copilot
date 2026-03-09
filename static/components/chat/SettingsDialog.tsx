"use client";

import { X, Sun, Moon, Monitor } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";

type SettingsDialogProps = {
  open: boolean;
  onClose: () => void;
};

export function SettingsDialog({ open, onClose }: SettingsDialogProps) {
  const { theme, setTheme } = useTheme();

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
                当前 Web 页面仅保留外观设置。
              </CardDescription>
            </div>
            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          </div>
        </CardHeader>

        <CardContent className="space-y-6 py-6">
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
