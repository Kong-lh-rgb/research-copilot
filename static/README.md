# AI Agent 前端（Next.js App Router）

一个用于展示 AI 思考过程、工具调用与任务执行流程的现代化前端界面。

## 技术栈

- Next.js (App Router)
- TypeScript
- TailwindCSS + shadcn/ui
- Framer Motion
- SSE Streaming (可切换 Mock)

## 本地启动

```bash
npm run dev
```

默认访问：http://localhost:3000

## Streaming 配置

- 默认启用 Mock 流式数据
- 连接后端 SSE：

```bash
NEXT_PUBLIC_USE_MOCK=false
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

并确保后端提供 `POST /chat/stream` SSE 流（例如：`http://localhost:8000/chat/stream`）。

## 目录结构

```
app/
  layout.tsx
  page.tsx
components/
  chat/
  ui/
  theme-provider.tsx
hooks/
  useChatStream.ts
lib/
  types.ts
  mockStream.ts
```

## 组件说明

- ChatContainer: 页面主体
- ChatMessage / UserMessage / AIMessage: 对话消息
- ThinkingPanel: 思考过程折叠面板
- ToolCallCard: 工具调用卡片
- TaskProgressPanel: 任务执行面板
- ChatInput: 输入区（Enter 发送 / Shift+Enter 换行）
- StreamingText: 打字机效果

## 注意

如需替换 UI 文案、工具字段或任务结构，可修改 `lib/types.ts` 与 `hooks/useChatStream.ts` 的事件映射逻辑。
