#原生openai sdk实现提取用户的需求意图，生成任务列表，并将任务列表存储在状态中
import logging
from typing import Any, Dict, List, Optional
from app.llm.wrapper import call_llm
from app.graph.state import AgentState
from app.llm.prompts import PLANNER_PROMPTS

logger = logging.getLogger(__name__)

def planner_node(state:AgentState)->dict:
    try:
        user_input = state.get("user_input", "")
        if not user_input:
            raise ValueError("用户输入为空，无法生成任务列表")

        system = PLANNER_PROMPTS
        res = call_llm(
            messages=[{"role":"user", "content": user_input}],
            system=system
        )
        if res.get("error"):
            raise ValueError(res["error"])
        
        content = res.get("content", "")
        logger.info(f"解析用户输入生成任务列表：{content}")
        return {"task_list": content}
    
    except Exception as e:
        logger.error(f"❌ [Planner] 解析大模型生成任务列表失败: {e}")
        return {"task_list": []}