import logging
import json
import re
from app.graph.prompts import CONTROLLER_PROMPTS
from app.infrastructure.llm.llm import get_llm
from app.graph.state import AgentState


logger = logging.getLogger(__name__)

def controller_node(state: AgentState) -> dict:
    user_input = state.get("user_input","")
    logger.info(f"接收用户请求：{user_input}")

    client = get_llm()
    full_prompt = CONTROLLER_PROMPTS.format(user_input=user_input)

    try:
        res = client.chat(
            messages=[{"role": "user", "content": full_prompt}]
        )
        choices = res.get("choices", [])
        answer = ""
        if choices:
            answer = (choices[0].get("message", {}) or {}).get("content", "") or ""

        if not answer:
            raise ValueError("模型未返回可解析的文本内容")

        clean_text = answer.replace("```json", "").replace("```", "").strip()
        if not clean_text.startswith("{"):
            match = re.search(r"\{[\s\S]*\}", clean_text)
            if match:
                clean_text = match.group(0)

        result = json.loads(clean_text)

        intent = result.get("intent")
        logger.info(f"解析用户意图：{intent}")

        if intent == "complex_research":
            return {
                "next_action": "complex_research",
            }
        else:
            return {
                "next_action":"simple_chat",
            }
            
    except Exception as e:
        logger.error(f"❌ [Controller] 解析大模型路由指令失败: {e}")
        logger.warning("🛡️ 触发兜底机制：默认将其视为复杂任务进入调研流。")
        # 兜底容错：哪怕 JSON 解析炸了，业务不能停，硬着头皮让 Planner 去处理
        return {
            "next_action": "planner"
        }



