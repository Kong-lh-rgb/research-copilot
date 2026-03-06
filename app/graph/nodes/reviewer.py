import asyncio
import logging
from app.graph.state import AgentState
from app.llm.wrapper import call_llm_stream

logger = logging.getLogger(__name__)

REVIEWER_PROMPT_TEXT = """你是一个专业的研究报告汇总员。
你的任务是将多个分任务的执行结果整合成一份结构清晰、逻辑连贯的最终报告。
要求：
1. 直接输出报告内容，不要有多余的元叙述
2. 保留关键数据和结论
3. 如果各任务结果已经成体系，按逻辑顺序整合即可
4. 使用 Markdown 格式（标题、表格、段落等）
"""


def _get_queue(thread_id: str) -> asyncio.Queue | None:
    if not thread_id:
        return None
    try:
        from app.main import app as _app
        return getattr(_app.state, "stream_queues", {}).get(thread_id)
    except Exception:
        return None


async def reviewer_node(state: AgentState) -> dict:
    """从 state 全局字典获取 thread_id（LangGraph官方推荐的稳妥做法）。"""
    thread_id = state.get("thread_id", "")
    queue = _get_queue(thread_id)

    task_results = state.get("task_results") or {}
    if task_results:
        results = [v for v in task_results.values() if v]
    else:
        results = [t.result for t in (state.get("tasks") or {}).values() if t.result]

    logger.info(f"✅ [Reviewer] 开始汇总，共 {len(results)} 个任务结果")

    if not results:
        return {"final_report": "", "messages": []}

    if len(results) == 1:
        content = results[0]
        if queue is not None:
            # 分块推送，避免把整段内容当单个 token 一次性塞入队列
            chunk_size = 80
            for i in range(0, len(content), chunk_size):
                queue.put_nowait({"type": "content_token", "delta": content[i:i + chunk_size]})
                await asyncio.sleep(0)  # 让事件循环有机会调度 _drain
            queue.put_nowait(None)
    else:
        combined = "\n\n---\n\n".join(results)
        messages = [
            {"role": "user", "content": f"以下是各子任务的执行结果，请整合成一份报告：\n\n{combined}"}
        ]
        full_content = ""
        async for chunk in call_llm_stream(messages=messages, system=REVIEWER_PROMPT_TEXT):
            if chunk.get("done"):
                break
            c = chunk.get("content", "")
            if c:
                full_content += c
                if queue is not None:
                    queue.put_nowait({"type": "content_token", "delta": c})
        if queue is not None:
            queue.put_nowait(None)
        content = full_content or combined

    logger.info(f"✅ [Reviewer] 汇总完成")
    return {
        "final_report": content,
        "messages": [{"role": "assistant", "content": content}],
    }
