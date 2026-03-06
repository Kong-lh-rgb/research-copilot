"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

type StreamingTextProps = {
  text: string;
  isStreaming?: boolean;
};

/**
 * 流式打字机效果：实时渲染 Markdown + 闪烁光标
 * - 流式阶段：逐字符累加显示，支持 Markdown 实时渲染
 * - 历史消息：直接渲染完整内容
 */
export function StreamingText({ text, isStreaming = false }: StreamingTextProps) {
  return (
    <div className="prose prose-sm max-w-none dark:prose-invert">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
        {text || "AI 正在思考..."}
      </ReactMarkdown>
      {isStreaming && (
        <span
          className="inline-block w-[2px] h-[1em] ml-[2px] align-middle bg-current animate-pulse"
          aria-hidden="true"
        />
      )}
    </div>
  );
}
