from typing import Any, Dict, List, TypedDict, Annotated

class Message(TypedDict):
    role: str
    content: str


class AgentState(TypedDict, total=False):
    message: List[Message]
    thread_id: str
    user_input: str
    tasks: Annotated[List[Dict[str, Any]], {"description": "任务列表"}]
    review_feedback: str
    loop_count: int
    final_report: str
    next_action: str