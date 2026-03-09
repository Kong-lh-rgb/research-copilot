import asyncio
import logging
from app.graph.state import AgentState
from app.llm.wrapper import call_llm_stream
from langchain_core.runnables import RunnableConfig
from app.llm.prompt_manager import render

logger = logging.getLogger(__name__)


def _build_failure_summary(tasks: dict) -> str:
    """当存在失败任务时，生成用户可读的错误总结。

    区分两类失败：
    - [需补充信息]：工具已接入但缺少用户提供的参数（邮箱、手机号等）
    - 其他：工具未接入或配置问题

    已完成任务的完整结果也会附在输出中，确保下一轮对话历史里能找到。
    """
    failed_info_parts: list[str] = []   # 缺少用户信息
    failed_tool_parts: list[str] = []   # 缺少工具/配置
    completed_results: list[tuple[str, str]] = []  # (description, result)

    for tid, t in tasks.items():
        if t.status == "failed":
            error = t.error or "未知错误"
            display_error = error.replace("[需补充信息] ", "", 1)
            entry = f"- **{tid}**（{t.description}）\n  - {display_error}"
            if "[需补充信息]" in error:
                failed_info_parts.append(entry)
            else:
                failed_tool_parts.append(entry)
        elif t.status == "completed" and t.result:
            completed_results.append((t.description, t.result))

    lines = ["## ⚠️ 任务执行未完成\n"]

    if failed_info_parts:
        lines.append(f"以下 {len(failed_info_parts)} 个子任务需要您补充信息才能继续：\n")
        lines.extend(failed_info_parts)
        lines.append("\n**➡️ 请在下一条消息中提供上述缺少的信息，我将重新为您执行。**")

    if failed_tool_parts:
        if failed_info_parts:
            lines.append("")
        lines.append(f"以下 {len(failed_tool_parts)} 个子任务因配置问题无法完成：\n")
        lines.extend(failed_tool_parts)
        lines.append("\n请检查配置（如 `mcp_servers.json`、MCP 服务是否启动、工具名称是否正确），修复后重试。")

    # 把已完成任务的完整结果附到消息里
    # 目的：当用户在下一轮补充信息后，worker 可以从对话历史中找到这份报告内容
    if completed_results:
        lines.append("\n---\n\n## 已完成任务的分析结果（供后续使用）\n")
        for desc, result in completed_results:
            lines.append(f"### {desc}\n\n{result}\n")

    return "\n".join(lines)


async def reviewer_node(state: AgentState, config: RunnableConfig) -> dict:
    queue = config.get("configurable", {}).get("stream_queue")
    tasks: dict = state.get("tasks") or {}

    # ── 失败快速返回：有任意任务失败就生成错误总结 ───────────────────────────
    failed_tasks = {tid: t for tid, t in tasks.items() if t.status == "failed"}
    if failed_tasks:
        logger.warning(f"⚠️ [Reviewer] 检测到 {len(failed_tasks)} 个失败任务，生成错误总结")
        content = _build_failure_summary(tasks)
        if queue:
            chunk_size = 80
            for i in range(0, len(content), chunk_size):
                queue.put_nowait({"type": "content_token", "delta": content[i:i + chunk_size]})
                await asyncio.sleep(0)
        return {
            "final_report": content,
            "messages": [{"role": "assistant", "content": content}],
        }

    task_results = state.get("task_results") or {}
    if task_results:
        results = [v for v in task_results.values() if v]
    else:
        results = [t.result for t in tasks.values() if t.result]

    logger.info(f"✅ [Reviewer] 开始汇总，共 {len(results)} 个任务结果")

    if not results:
        return {"final_report": "", "messages": []}

    user_input = state.get("user_input") or ""

    if len(results) == 1:
        content = results[0]
        if queue:
            # 分块推送（避免单次推送过大内容）
            chunk_size = 80
            for i in range(0, len(content), chunk_size):
                queue.put_nowait({"type": "content_token", "delta": content[i:i + chunk_size]})
                await asyncio.sleep(0)  # 让事件循环有机会调度 _drain
    else:
        combined = "\n\n---\n\n".join(results)
        user_message = (
            f"【用户的原始需求】\n{user_input}\n\n"
            f"【各子任务执行结果】\n{combined}"
        )
        messages = [
            {"role": "user", "content": user_message}
        ]
        full_content = ""
        async for chunk in call_llm_stream(messages=messages, system=render("reviewer"), temperature=0.3, role="reviewer"):
            if chunk.get("done"):
                break
            c = chunk.get("content", "")
            if c:
                full_content += c
                if queue:
                    queue.put_nowait({"type": "content_token", "delta": c})
        content = full_content or combined

    return {
        "final_report": content,
        "messages": [{"role": "assistant", "content": content}],
    }