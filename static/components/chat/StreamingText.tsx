"use client";

type StreamingTextProps = {
  text: string;
  isStreaming?: boolean;
};

/**
 * 流式阶段：直接渲染已收到的文字 + 闪烁光标，不做 CSS 打字机动画
 * （CSS 动画在每个新 token 到来时都会重置，导致用户看到"全部内容最后一秒跳出"的错觉）
 * 历史消息（isStreaming=false）：不带光标，直接渲染
 */
export function StreamingText({ text, isStreaming = false }: StreamingTextProps) {
  if (!isStreaming) {
    return <span>{text}</span>;
  }

  return (
    <span>
      {text}
      <span
        className="inline-block w-[2px] h-[1em] ml-[1px] align-middle bg-current animate-pulse"
        aria-hidden="true"
      />
    </span>
  );
}
