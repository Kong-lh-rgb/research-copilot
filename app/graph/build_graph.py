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
    action = state.get("next_action")
    if action == "complex_research":
        return "planner"
    elif action == "resume_research":
        return "resumer"
    else:
        return "simple_chat"

def resumer_node(state: AgentState) -> dict:
    """恢复被中断的任务执行。
    
    将 running 任务改为 pending，以便 Distributor 能派发它们重新执行。
    """
    tasks = state.get("tasks") or {}
    
    # 统计任务状态
    running_tasks = [tid for tid, t in tasks.items() if getattr(t, "status", "") == "running"]
    pending_tasks = [tid for tid, t in tasks.items() if getattr(t, "status", "") == "pending"]
    completed = [tid for tid, t in tasks.items() if getattr(t, "status", "") == "completed"]
    
    logger.info(f"🔄 [Resumer] 恢复被中断任务: {len(running_tasks)} running → pending, {len(pending_tasks)} pending, {len(completed)} completed")
    
    # ⚠️ 关键：将所有 running 任务改为 pending，以便重新派发
    for tid in running_tasks:
        task = tasks[tid]
        task.status = "pending"
        logger.info(f"  ↩️ {tid}: running → pending")
    
    # 计算现在有哪些任务可以执行（依赖都已完成）
    ready_tasks = []
    for tid in running_tasks + pending_tasks:
        task = tasks.get(tid)
        if not task:
            continue
        
        # 获取任务的依赖列表
        dependencies = getattr(task, "dependencies", None) or []
        
        # 检查所有依赖是否已完成
        if all(dep in completed for dep in dependencies):
            ready_tasks.append(tid)
            logger.info(f"  ✓ {tid} 可就绪（依赖已满足）")
        else:
            waiting = [dep for dep in dependencies if dep not in completed]
            logger.info(f"  ⏳ {tid} 等待依赖：{waiting}")
    
    return {
        "tasks": tasks,  # 返回修改后的 tasks（running 改为 pending）
        "ready_tasks": ready_tasks
    }

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
    suspended = sum(1 for t in tasks.values() if t.status == "suspended")
    running   = sum(1 for t in tasks.values() if t.status == "running")
    total     = len(tasks)

    # ① 如果有挂起任务且无其他运行中的任务，挂起执行，等待用户输入（不进入审查总结）
    if suspended > 0 and running == 0:
        logger.info(f"⏸️ [Distributor] 检测到 {suspended} 个挂起任务，中断执行等待用户输入")
        return END

    # ② 有任务失败 → 进入 reviewer 生成失败总结（而非直接 END）
    if failed > 0:
        logger.error(f"🛑 [Distributor] 检测到 {failed} 个失败任务，中断执行，转入 reviewer 生成错误总结")
        return "reviewer"

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
    graph.add_node("resumer", resumer_node)
    graph.set_entry_point("controller")

    graph.add_conditional_edges(
        "controller",
        router_after_controller,
        {
            "simple_chat": "simple_chat",
            "planner": "planner",
            "resumer": "resumer"
        }
    )
    
    graph.add_conditional_edges(
        "resumer",
        distribute_tasks,
        ["worker", "reviewer", END]
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

