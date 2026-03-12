from typing import Any, Dict, List, TypedDict, Annotated, Optional

from pydantic import BaseModel, Field
from langgraph.graph.message import add_messages



class TaskNode(BaseModel):
    task_id: str
    description: str
    status: str = "pending"
    dependencies: List[str] = Field(default_factory=list)
    result: Optional[str] = None
    error: Optional[str] = None


class ToolCall(TypedDict):
    task_id: str
    tool_name: str
    arguments: str   # JSON 字符串
    output: str      # 截断后的工具输出


def merge_dicts(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    """通用 dict 合并 reducer：右侧覆盖左侧，用于并行 worker 写入。
    支持传入 {"__clear__": True, ...} 来清空旧状态。
    """
    if right is not None and right.get("__clear__", False):
        new_dict = dict(right)
        new_dict.pop("__clear__", None)
        return new_dict
    
    merged = dict(left or {})
    merged.update(right or {})
    return merged


def concat_lists(left: Optional[List], right: Optional[List]) -> List:
    """None 安全的列表拼接 reducer，防止 checkpointer 恢复时 left=None 报错。
    支持传入 ["__clear__", ...] 来清空旧状态。
    """
    if right and right[0] == "__clear__":
        return right[1:]
    return (left or []) + (right or [])


def take_last(left: Any, right: Any) -> Any:
    """取最后一个值的 reducer，用于并发更新时只保留最新值。"""
    return right if right is not None else left


def set_union(left: Optional[List[str]], right: Optional[List[str]]) -> List[str]:
    """集合并集 reducer：合并两个列表，去重，顺序稳定。
    用于并行 worker 同时向 ready_tasks 写入新解锁的任务 ID，防止重复。
    支持传入 ["__clear__", ...] 来清空旧状态。
    """
    if right and "__clear__" in right:
        return [x for x in right if x != "__clear__"]
        
    base = list(left or [])
    seen = set(base)
    for item in (right or []):
        if item not in seen:
            base.append(item)
            seen.add(item)
    return base


def add_int(left: Optional[int], right: Optional[int]) -> int:
    """整数累加 reducer，用于并行 worker 各自累计完成/失败计数。"""
    return (left or 0) + (right or 0)


class AgentState(TypedDict, total=False):
    # ── 对话记录（仅 user / assistant 消息，由 add_messages 自动追加）
    messages: Annotated[List[Any], add_messages]

    # ── 执行状态
    thread_id: str
    user_input: str
    next_action: str
    current_task_id: Annotated[str, take_last]  # 支持并发更新

    # ── 任务图（planner 生成，controller 调度，worker 更新 status/result）
    tasks: Annotated[Dict[str, Any], merge_dicts]

    # ── 工具调用日志（worker 每次调用工具后追加）
    tool_history: Annotated[List[Any], concat_lists]

    # ── 任务执行结果（task_id → LLM 综合回答，reviewer 汇总用）
    task_results: Annotated[Dict[str, Any], merge_dicts]

    # ── 最终报告（reviewer / simple_chat 写入）
    final_report: Annotated[str, take_last]

    # ── 任务调度队列（planner 初始化，worker 完成后更新）
    # set_union 保证并行 worker 同时写入时不产生重复 ID
    ready_tasks: Annotated[List[str], set_union]

    # running_tasks 仅供调试/UI 展示，不参与核心调度逻辑
    running_tasks: Annotated[List[str], set_union]