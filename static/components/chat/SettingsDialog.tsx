"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardFooter, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

type SettingsValues = {
  model: string;
  apiKey: string;
  baseUrl: string;
  mcpCommand: string;
};

type SettingsDialogProps = {
  open: boolean;
  onClose: () => void;
};

const STORAGE_KEY = "deep-research-settings";

export function SettingsDialog({ open, onClose }: SettingsDialogProps) {
  const [values, setValues] = useState<SettingsValues>({
    model: "gpt-4o-mini",
    apiKey: "",
    baseUrl: "",
    mcpCommand: "",
  });

  useEffect(() => {
    if (!open) return;
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        setValues((prev) => ({ ...prev, ...JSON.parse(raw) }));
      }
    } catch {
      // ignore
    }
  }, [open]);

  const updateField = (key: keyof SettingsValues, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = () => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(values));
    } catch {
      // ignore
    }
    onClose();
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
                配置模型、API 和 MCP 工具。当前为本地保存的简单设置页面。
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
              <h3 className="text-sm font-semibold text-foreground">模型配置</h3>
              <p className="mt-1 text-xs text-muted-foreground">选择项目默认模型并填写接口信息。</p>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <label className="space-y-2 text-sm">
                <span className="text-foreground">模型名称</span>
                <select
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
                  value={values.model}
                  onChange={(event) => updateField("model", event.target.value)}
                >
                  <option value="gpt-4o-mini">gpt-4o-mini</option>
                  <option value="gpt-4.1-mini">gpt-4.1-mini</option>
                  <option value="deepseek-chat">deepseek-chat</option>
                  <option value="qwen-max">qwen-max</option>
                  <option value="glm-4-plus">glm-4-plus</option>
                </select>
              </label>
              <label className="space-y-2 text-sm">
                <span className="text-foreground">接口地址</span>
                <Input
                  placeholder="例如：https://api.openai.com/v1"
                  value={values.baseUrl}
                  onChange={(event) => updateField("baseUrl", event.target.value)}
                />
              </label>
            </div>
            <label className="block space-y-2 text-sm">
              <span className="text-foreground">API 密钥</span>
              <Input
                type="password"
                placeholder="输入模型 API 密钥"
                value={values.apiKey}
                onChange={(event) => updateField("apiKey", event.target.value)}
              />
            </label>
          </section>

          <Separator />

          <section className="space-y-4">
            <div>
              <h3 className="text-sm font-semibold text-foreground">MCP 工具</h3>
              <p className="mt-1 text-xs text-muted-foreground">可填写 MCP 启动命令或服务地址，后续可接入真实保存接口。</p>
            </div>
            <label className="block space-y-2 text-sm">
              <span className="text-foreground">MCP 工具配置</span>
              <Input
                placeholder="例如：python run_server.py 或 http://127.0.0.1:8001"
                value={values.mcpCommand}
                onChange={(event) => updateField("mcpCommand", event.target.value)}
              />
            </label>
          </section>
        </CardContent>

        <CardFooter className="justify-end gap-3 border-t border-border/60 py-4">
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button onClick={handleSave}>保存</Button>
        </CardFooter>
      </Card>
    </div>
  );
}
