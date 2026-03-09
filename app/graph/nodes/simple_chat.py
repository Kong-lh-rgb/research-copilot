import asyncio
import logging
from langchain_core.runnables import RunnableConfig
from app.llm.wrapper import call_llm_stream
from app.graph.state import AgentState
from app.llm.prompt_manager import render

logger = logging.getLogger(__name__)


def _to_openai_dict(m) -> dict:
    if isinstance(m, dict):
        return m
    role = {"human": "user", "ai": "assistant", "system": "system"}.get(
        getattr(m, "type", ""), "user"
    )
    return {"role": role, "content": getattr(m, "content", "")}


def _build_tool_context(state: AgentState) -> str:
    history = state.get("tool_history") or []
    if not history:
        return ""
    lines = []
    for item in history[-20:]:
        tc = item if isinstance(item, dict) else dict(item)
        snippet = tc.get("output", "")[:100].replace("\n", " ")
        lines.append(
            f"  - [{tc.get('task_id', '')}] {tc.get('tool_name', '')}({tc.get('arguments', '')}) → {snippet}"
        )
    return "\n\n【本轮使用的工具（摘要）】\n" + "\n".join(lines) + "\n"


async def simple_chat_node(state: AgentState, config: RunnableConfig) -> dict:
    # 核心修改：从 config 安全获取 queue
    queue = config.get("configurable", {}).get("stream_queue")

    messages = [_to_openai_dict(m) for m in state.get("messages", [])]
    system = render("simple_chat") + _build_tool_context(state)
    full_content = ""

    async for chunk in call_llm_stream(messages=messages, system=system, temperature=0.3, role="simple_chat"):
        if chunk.get("done"):
            break
        c = chunk.get("content", "")
        if c:
            full_content += c
            if queue:
                queue.put_nowait({"type": "content_token", "delta": c})

    content = full_content or ""
    return {
        "final_report": content,
        "messages": [{"role": "assistant", "content": content}],
    }
