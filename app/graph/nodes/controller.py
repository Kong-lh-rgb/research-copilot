import logging
import json
import re
from app.llm.prompt_manager import render
from app.llm.wrapper import call_llm
from app.graph.state import AgentState


logger = logging.getLogger(__name__)

#确保大模型返回标准意图判断
def _parse_intent_from_text(answer: str) -> str:
    if not answer:
        raise ValueError("模型未返回可解析的文本内容")

    clean_text = answer.replace("```json", "").replace("```", "").strip()
    if not clean_text.startswith("{"):
        match = re.search(r"\{[\s\S]*\}", clean_text)
        if match:
            clean_text = match.group(0)

    result = json.loads(clean_text)
    return result.get("intent", "")


async def controller_node(state: AgentState) -> dict:
    user_input = state.get("user_input", "")
    logger.info(f"接收用户请求：{user_input}")

    tasks = state.get("tasks") or {}
    suspended_tasks = {tid: t for tid, t in tasks.items() if getattr(t, "status", "") == "suspended"}

    if suspended_tasks:
        logger.info(f"🔄 发现挂起任务: {list(suspended_tasks.keys())}，将尝试以用户输入恢复执行")
        updates = {}
        for tid, t in suspended_tasks.items():
            t.status = "pending"
            t.error = None
            t.description += f"\n\n[用户补充信息]: {user_input}"
            updates[tid] = t
        return {
            "next_action": "resume_research",
            "tasks": updates,
            "ready_tasks": list(suspended_tasks.keys())
        }

    try:
        system_prompt = render("controller")
        res = await call_llm(
            messages=[{"role": "user", "content": user_input}],
            system=system_prompt,
            role="controller",
            temperature=0.2,
        )
        if res.get("error"):
            raise ValueError(res["error"])

        intent = _parse_intent_from_text(res.get("content", "") or "")
        logger.info(f"解析用户意图：{intent}")

        next_action = "complex_research" if intent == "complex_research" else "simple_chat"
        return {"next_action": next_action}
            
    except Exception as e:
        logger.error(f"❌ [Controller] 解析大模型路由指令失败: {e}")
        logger.warning("🛡️ 触发兜底机制：默认将其视为复杂任务进入调研流。")
        return {
            "next_action": "complex_research"
        }



