def build_tool_evidence_summary(tool_calls: list[dict], max_items: int = 8) -> str:
    if not tool_calls:
        return ""

    lines = ["\n\n---\n\n## 引用来源 / 工具证据摘要"]
    for idx, item in enumerate(tool_calls[:max_items], start=1):
        tool_name = str(item.get("tool_name", "")).strip() or "unknown_tool"
        raw_args = str(item.get("arguments", "")).strip() or "{}"
        raw_output = str(item.get("output", "")).replace("\n", " ").strip()
        output_excerpt = (raw_output[:140] + "…") if len(raw_output) > 140 else raw_output
        lines.append(f"{idx}. **{tool_name}**")
        lines.append(f"   - 参数：`{raw_args}`")
        lines.append(f"   - 证据摘录：{output_excerpt or '（无输出）'}")

    if len(tool_calls) > max_items:
        lines.append(f"\n> 其余 {len(tool_calls) - max_items} 条工具调用已省略。")

    return "\n".join(lines)
