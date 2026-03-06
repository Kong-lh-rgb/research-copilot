import asyncio
import logging
from app.llm.wrapper import call_llm_stream
from app.graph.state import AgentState
from app.llm.prompts import SIMPLE_CHAT_PROMPT

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


def _get_queue(thread_id: str) -> asyncio.Queue | None:
    if not thread_id:
        return None
    try:
        from app.main import app as _app
        return getattr(_app.state, "stream_queues", {}).get(thread_id)
    except Exception:
        return None


async def simple_chat_node(state: AgentState) -> dict:
    """从 state 全局字典获取 thread_id（LangGraph官方推荐的稳妥做法）。"""
    thread_id = state.get("thread_id", "")
    queue = _get_queue(thread_id)

    messages = [_to_openai_dict(m) for m in state.get("messages", [])]
    system = SIMPLE_CHAT_PROMPT + _build_tool_context(state)

    full_content = ""

    async for chunk in call_llm_stream(messages=messages, system=system):
        if chunk.get("done"):
            break
        t = chunk.get("thinking", "")
        c = chunk.get("content", "")
        if t and queue is not None:
            queue.put_nowait({"type": "thinking_token", "delta": t})
        if c:
            full_content += c
            if queue is not None:
                queue.put_nowait({"type": "content_token", "delta": c})

    if queue is not None:
        queue.put_nowait(None)

    content = full_content or ""
    logger.info(f"[SimpleChat] 回复长度: {len(content)}")
    return {
        "final_report": content,
        "messages": [{"role": "assistant", "content": content}],
    }
