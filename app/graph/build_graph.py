import logging
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from app.graph.nodes.controller import controller_node
from app.graph.nodes.simple_chat import simple_chat_node
from app.graph.nodes.planner import planner_node
from app.graph.nodes.reviewer import reviewer_node
from app.graph.nodes.worker import worker_node
from app.graph.state import AgentState, TaskNode

logger = logging.getLogger(__name__)


def router_after_controller(state: AgentState) -> str:
    return "planner" if state.get("next_action") == "complex_research" else "simple_chat"

def distribute_tasks(state: AgentState):
    """基于 ready_tasks 队列派发 worker，O(k)（k = 当前就绪任务数）。

    终止条件从 tasks dict 直接推导，避免依赖可能被 checkpointer
    跨轮次污染的计数器字段。tasks dict 的 n 通常很小（5~20），O(n) 可接受。
    """
    tasks       = state.get("tasks") or {}
    ready_tasks = state.get("ready_tasks") or []

    if not tasks:
        logger.warning("⚠️ [Distributor] tasks 为空，终止执行")
        return END

    # 从 tasks dict 实时推导状态计数（防止 add_int 跨对话污染）
    completed = sum(1 for t in tasks.values() if t.status == "completed")
    failed    = sum(1 for t in tasks.values() if t.status == "failed")
    running   = sum(1 for t in tasks.values() if t.status == "running")
    total     = len(tasks)

    # ① 有任务失败 → 立即终止
    if failed > 0:
        logger.error(f"🛑 [Distributor] 检测到 {failed} 个失败任务，中断执行")
        return END

    # ② 全部完成 → 进入 reviewer
    if completed >= total:
        logger.info(f"✅ [Distributor] 所有 {total} 个任务已完成，进入 reviewer")
        return "reviewer"

    # ③ 从 ready_tasks 中筛出仍处于 pending 状态的任务（过滤已 dispatched/running/completed 的）
    pending_ready = [
        tid for tid in ready_tasks
        if tasks.get(tid) and tasks[tid].status == "pending"
    ]

    if not pending_ready:
        if running > 0:
            logger.info(f"⏳ [Distributor] 无新就绪任务，等待 {running} 个运行中任务完成...")
            return []
        logger.warning("⚠️ [Distributor] 无就绪任务且无运行中任务，终止执行")
        return END

    logger.info(f"🚀 [Distributor] 将并行启动 {len(pending_ready)} 个就绪任务: {pending_ready}")
    return [
        Send("worker", {"current_task_id": tid, "tasks": tasks})
        for tid in pending_ready
    ]


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("controller", controller_node)
    graph.add_node("simple_chat", simple_chat_node)
    graph.add_node("planner", planner_node)
    graph.add_node("worker", worker_node)
    graph.add_node("reviewer", reviewer_node)
    graph.set_entry_point("controller")

    graph.add_conditional_edges(
        "controller",
        router_after_controller,
        {
            "simple_chat": "simple_chat",
            "planner": "planner"
        }
    )
    
    graph.add_conditional_edges(
        "planner",
        distribute_tasks,
        ["worker", "reviewer", END]
    )

    graph.add_conditional_edges(
        "worker",
        distribute_tasks,
        ["worker", "reviewer", END]
    )


    graph.add_edge("reviewer", END)
    graph.add_edge("simple_chat", END)

    return graph

