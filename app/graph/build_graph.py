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
    tasks = state.get("tasks", {})
    sends = []
    all_completed = True
    has_running = False

    for task_id, task_node in tasks.items():
        if task_node.status == "failed":
            logger.error(f"🛑 [Distributor] 任务 [{task_id}] 失败: {task_node.error}，中断图执行")
            return END

        if task_node.status != "completed":
            all_completed = False
        
        if task_node.status == "running":
            has_running = True

        deps_done = all(
            tasks[dep].status == "completed"
            for dep in (task_node.dependencies or [])
        )

        if task_node.status == "pending" and deps_done:
            logger.info(f"🚀 [Distributor] 启动任务 [{task_id}]: {task_node.description[:50]}")
            # ⚠️ 必须显式传递 tasks，否则 worker 读取不到任务字典
            sends.append(Send("worker", {"current_task_id": task_id, "tasks": tasks}))

    if all_completed and tasks:
        logger.info("✅ [Distributor] 所有任务已完成，进入 reviewer")
        return "reviewer"

    if sends:
        return sends

    # 🔧 修复：如果还有任务在运行中，返回空 sends 让图继续等待（不要返回 END）
    if has_running:
        logger.info(f"⏳ [Distributor] 还有任务正在执行中，等待完成...")
        return []

    logger.warning("⚠️ [Distributor] 没有可执行的任务，结束执行")
    return END
    
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

