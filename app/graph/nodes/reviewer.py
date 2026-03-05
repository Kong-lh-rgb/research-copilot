import logging
from app.graph.state import AgentState

logger = logging.getLogger(__name__)

async def reviewer_node(state: AgentState) -> dict:
    # 优先从扁平化的 task_results 读取，降级到 TaskNode.result（兼容旧状态）
    task_results = state.get("task_results") or {}
    if task_results:
        results = [v for v in task_results.values() if v]
    else:
        results = [t.result for t in (state.get("tasks") or {}).values() if t.result]

    final_report = "\n\n".join(results)
    logger.info(f"✅ [Reviewer] 汇总完成，共 {len(results)} 个任务结果")
    return {
        "final_report": final_report,
        "messages": [{"role": "assistant", "content": final_report}],
    }
