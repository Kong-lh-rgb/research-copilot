from typing import Any, Dict, List, TypedDict, Annotated, Optional
from dataclasses import dataclass, field


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


def merge_tasks(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    """多个 worker 并行写入 tasks 时，用右侧的值覆盖左侧（保留最新状态）"""
    merged = dict(left or {})
    merged.update(right or {})
    return merged


class AgentState(TypedDict, total=False):
    message: List[Message]
    thread_id: str
    user_input: str
    tasks: Annotated[Dict[str, TaskNode], merge_tasks]
    review_feedback: str
    loop_count: int
    final_report: str
    next_action: str
    current_task_id: str