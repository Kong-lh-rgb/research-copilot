import logging
from app.llm.wrapper import call_llm
from app.graph.state import AgentState
from app.llm.prompts import SIMPLE_CHAT_PROMPT

logger = logging.getLogger(__name__)


def _to_openai_dict(m) -> dict:
    """add_messages reducer 将 dict 转为 LangChain BaseMessage 对象，此处统一转回 dict。"""
    if isinstance(m, dict):
        return m
    role = {"human": "user", "ai": "assistant", "system": "system"}.get(
        getattr(m, "type", ""), "user"
    )
    return {"role": role, "content": getattr(m, "content", "")}


def _build_tool_context(state: AgentState) -> str:
    """从 tool_history 提取紧凑摘要注入 system prompt，不暴露完整 state。"""
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


async def simple_chat_node(state: AgentState) -> dict:
    messages = [_to_openai_dict(m) for m in state.get("messages", [])]
    system = SIMPLE_CHAT_PROMPT + _build_tool_context(state)
    res = await call_llm(messages=messages, system=system)
    content = res.get("content", "")
    logger.info(f"[SimpleChat] 回复: {content}")
    return {
        "final_report": content,
        "messages": [{"role": "assistant", "content": content}],
    }
