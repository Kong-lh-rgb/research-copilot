#原生openai sdk实现提取用户的需求意图，生成任务列表，并将任务列表存储在状态中
import json
import logging
import re
from typing import Any, Dict, List, Optional
from app.llm.wrapper import call_llm
from app.graph.state import AgentState, TaskNode
from app.llm.prompts import PLANNER_PROMPTS

logger = logging.getLogger(__name__)

def _parse_tasks(content: str) -> Dict[str, TaskNode]:
    """将 LLM 返回的 JSON 字符串解析为 Dict[task_id, TaskNode]"""
    clean = content.strip()
    # 去掉可能的 markdown 代码块
    clean = re.sub(r"```[\w]*", "", clean).strip()
    task_list = json.loads(clean)
    return {
        t["task_id"]: TaskNode(
            task_id=t["task_id"],
            description=t["description"],
            dependencies=t.get("dependencies", []),
            status=t.get("status", "pending"),
        )
        for t in task_list
    }

async def planner_node(state:AgentState)->dict:
    try:
        user_input = state.get("user_input", "")
        if not user_input:
            raise ValueError("用户输入为空，无法生成任务列表")

        system = PLANNER_PROMPTS
        res = await call_llm(
            messages=[{"role":"user", "content": user_input}],
            system=system
        )
        if res.get("error"):
            raise ValueError(res["error"])
        
        content = res.get("content", "")
        logger.info(f"LLM 返回任务列表原文：{content}")
        tasks = _parse_tasks(content)
        logger.info(f"解析完成，共 {len(tasks)} 个任务: {list(tasks.keys())}")
        return {"tasks": tasks}
    
    except Exception as e:
        logger.error(f"❌ [Planner] 解析大模型生成任务列表失败: {e}")
        return {"tasks": {}}