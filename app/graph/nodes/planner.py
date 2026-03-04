#原生openai sdk实现提取用户的需求意图，生成任务列表，并将任务列表存储在状态中
import logging
from typing import Any, Dict, List, Optional
from app.llm.client import get_llm
from app.graph.state import AgentState

loggger = logging.getLogger(__name__)

def planner_node(state:AgentState)->AgentState:
    user_input = state.get("user_input", "")
    if not user_input:
        raise ValueError("用户输入为空，无法生成任务列表")
    client = get_llm()
    