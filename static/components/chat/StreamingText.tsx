"use client";

type StreamingTextProps = {
  text: string;
  isStreaming?: boolean;
  speed?: number;
};

export function StreamingText({ text, isStreaming = false, speed = 18 }: StreamingTextProps) {
  const steps = Math.max(text.length, 1);
  const duration = Math.min(6, Math.max(1.2, steps / speed));

  if (!isStreaming) {
    return <span>{text}</span>;
  }

  return (
    <span
      className="typing"
      style={
        {
          "--typing-steps": steps,
          "--typing-duration": `${duration}s`,
        } as React.CSSProperties
      }
    >
      {text}
    </span>
  );
}
