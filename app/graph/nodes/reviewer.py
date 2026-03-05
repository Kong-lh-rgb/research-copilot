import logging
from app.graph.state import AgentState

logger = logging.getLogger(__name__)

async def reviewer_node(state: AgentState) -> dict:
    tasks = state.get("tasks", {})
    results = [t.result for t in tasks.values() if t.result]
    final_report = "\n\n".join(results)
    logger.info(f"✅ [Reviewer] 汇总完成，共 {len(results)} 个任务结果")
    return {"final_report": final_report}
