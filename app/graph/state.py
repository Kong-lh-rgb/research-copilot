from typing import Any, Dict, List, TypedDict, Annotated, Optional
from dataclasses import dataclass, field
from langgraph.graph.message import add_messages


@dataclass
class TaskNode:
    task_id: str
    description: str
    status: str = "pending"
    dependencies: List[str] = field(default_factory=list)
    result: Optional[str] = None
    error: Optional[str] = None


class Message(TypedDict):
    role: str
    content: str


class ToolCall(TypedDict):
    task_id: str
    tool_name: str
    arguments: str   # JSON 字符串
    output: str      # 截断后的工具输出


def merge_dicts(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    """通用 dict 合并 reducer：右侧覆盖左侧，用于并行 worker 写入。"""
    merged = dict(left or {})
    merged.update(right or {})
    return merged


def concat_lists(left: Optional[List], right: Optional[List]) -> List:
    """None 安全的列表拼接 reducer，防止 checkpointer 恢复时 left=None 报错。"""
    return (left or []) + (right or [])


# 保留旧名称，避免破坏已有引用
merge_tasks = merge_dicts


class AgentState(TypedDict, total=False):
    # ── 对话记录（仅 user / assistant 消息，由 add_messages 自动追加）
    messages: Annotated[List[Message], add_messages]

    # ── 执行状态
    thread_id: str
    user_input: str
    next_action: str
    current_task_id: str
    loop_count: int

    # ── 任务图（planner 生成，controller 调度，worker 更新 status/result）
    tasks: Annotated[Dict[str, TaskNode], merge_dicts]

    # ── 工具调用日志（worker 每次调用工具后追加，concat_lists 拼接列表）
    tool_history: Annotated[List[ToolCall], concat_lists]

    # ── 任务执行结果（task_id → LLM 综合回答，reviewer 汇总用）
    task_results: Annotated[Dict[str, str], merge_dicts]

    # ── 工具原始输出（task_id → 所有工具调用的原始拼接，调试 / 引用用）
    observations: Annotated[Dict[str, str], merge_dicts]

    # ── 最终报告（reviewer / simple_chat 写入）
    final_report: str
    review_feedback: str