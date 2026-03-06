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

async def planner_node(state: AgentState) -> dict:
    try:
        user_input = state.get("user_input", "")
        if not user_input:
            raise ValueError("用户输入为空，无法生成任务列表")

        # 拼入最近历史对话让规划时感知上下文
        raw_messages = list(state.get("messages") or [])
        
        def _to_dict(m):
            if isinstance(m, dict):
                return m
            role = {"human": "user", "ai": "assistant"}.get(getattr(m, "type", ""), "user")
            return {"role": role, "content": getattr(m, "content", "")}
        
        history = [_to_dict(m) for m in raw_messages]
        # 只取最近 10 条以提升速度（减少 token 数量）
        planner_messages = history[-10:] if history else [{"role": "user", "content": user_input}]

        system = PLANNER_PROMPTS
        res = await call_llm(
            messages=planner_messages,
            system=system,
            temperature=0.2  # 稍微提高温度以加快生成速度
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