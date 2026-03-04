import logging
import json
import re
from app.llm.prompts import CONTROLLER_PROMPTS
from app.llm.wrapper import call_llm
from app.graph.state import AgentState


logger = logging.getLogger(__name__)


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


def controller_node(state: AgentState) -> dict:
    user_input = state.get("user_input", "")
    logger.info(f"接收用户请求：{user_input}")

    try:
        system_prompt = CONTROLLER_PROMPTS
        res = call_llm(
            messages=[{"role": "user", "content": user_input}],
            system=system_prompt
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
        # 兜底容错：哪怕 JSON 解析炸了，业务不能停，硬着头皮让 Planner 去处理
        return {
            "next_action": "planner"
        }



