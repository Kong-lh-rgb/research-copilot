export function TopBar() {
  return (
    <div className="flex items-center border-b border-border/60 bg-background/70 px-5 py-4 backdrop-blur">
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <span className="text-base">◎</span>
        </div>
        <div>
          <p className="text-sm font-semibold text-foreground">深度研究助手</p>
          <p className="text-xs text-muted-foreground">多步骤推理与工具调用助手</p>
        </div>
      </div>
    </div>
  );
}
