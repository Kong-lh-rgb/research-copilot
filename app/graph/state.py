from typing import Any, Dict, List, TypedDict, Annotated,Optional
from dataclasses import dataclass, field

@dataclass
class TaskNode:
    task_id: str
    description: str
    status: str = "pending"#running completed failed
    dependencies: List[str] = field(default_factory=list)
    result:Optional[str]=None
    error:Optional[str]=None


class Message(TypedDict):
    role: str
    content: str



class AgentState(TypedDict, total=False):
    message: List[Message]
    thread_id: str
    user_input: str
    tasks: Dict[str, TaskNode]
    review_feedback: str
    loop_count: int
    final_report: str
    next_action: str