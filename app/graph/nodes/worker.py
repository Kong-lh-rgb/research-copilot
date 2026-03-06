import json
import logging
from typing import List
from app.llm.wrapper import call_llm, mcp_tools_to_openai_tools
from app.graph.state import AgentState, ToolCall
from app.infrastructure.setup import tool_registry
from app.llm.prompts import WORKER_PROMPT

logger = logging.getLogger(__name__)

# 单个 Worker 任务内允许的最大 LLM ↔ Tool 交互轮数
MAX_TOOL_ROUNDS = 10


def _build_conversation_history(state: AgentState, max_messages: int = 20) -> str:
    """从 AgentState.messages 中提取近期对话历史（排除本轮用户消息），
    格式化为 Worker 可读的文本，让 Worker 能引用上一轮的分析结果。"""
    messages = state.get("messages") or []
    # messages 最后一条是本轮用户输入，排除它
    history = messages[:-1] if messages else []
    # 只取最近 max_messages 条
    history = history[-max_messages:]
    if not history:
        return "无"
    lines = []
    for m in history:
        if isinstance(m, dict):
            role = m.get("role", "")
            content = m.get("content", "") or ""
        else:
            # LangChain BaseMessage 对象
            role = getattr(m, "type", "")
            content = getattr(m, "content", "") or ""
        role_label = {"user": "用户", "human": "用户", "assistant": "AI", "ai": "AI"}.get(role, role)
        # 截断超长内容
        snippet = content[:2000] + ("…" if len(content) > 2000 else "")
        lines.append(f"[{role_label}]: {snippet}")
    return "\n".join(lines)


async def worker_node(state: AgentState) -> dict:
    tasks = state.get("tasks", {})
    task_id = state.get("current_task_id", "")
    if not task_id or task_id not in tasks:
        logger.error(f"❌ [Worker] 当前任务ID无效或不存在: {task_id}")
        return {"result": None, "error": f"当前任务ID无效或不存在: {task_id}"}
    task = tasks.get(task_id)
    if task.status != "running":
        return state
    try:
        user_input = state.get("user_input", "未提供")
        conversation_history = _build_conversation_history(state)

        
        dependencies_context = ""
        if task.dependencies:
            for dep_id in task.dependencies:
                dep_task = tasks.get(dep_id)
                if dep_task and dep_task.result:
                    dependencies_context += f"【前置任务 {dep_id} - {dep_task.description}】的结果是：\n{dep_task.result}\n\n"
        if not dependencies_context:
            dependencies_context = "无"

        system = WORKER_PROMPT.format(
            conversation_history=conversation_history,
            user_input=user_input,
            dependencies_context=dependencies_context,
            task_id=task.task_id,
            task_description=task.description
        )
        
        all_tools = await tool_registry.get_all_tools()
        openai_tools = mcp_tools_to_openai_tools(all_tools)
        logger.info(f"🛠️ [Worker] 可用工具: {[t['function']['name'] for t in openai_tools]}")

        messages = [{"role": "user", "content": task.description}]
        collected_tool_calls: List[ToolCall] = []

        # for...else：只有 break（即 not tool_calls）才会跳过 else 块
        for round_idx in range(MAX_TOOL_ROUNDS):
            result = await call_llm(
                messages=messages,
                system=system,
                tools=openai_tools if openai_tools else None,
            )
            if result.get("error"):
                raise ValueError(result["error"])

            tool_calls = result.get("tool_calls")

            if not tool_calls:
                task.result = result.get("content", "")
                break

            logger.info(f"🔧 [Worker] 第 {round_idx + 1} 轮，LLM 请求调用 {len(tool_calls)} 个工具")

            messages.append({
                "role": "assistant",
                "content": result.get("content") or "",
                "tool_calls": tool_calls,
            })

            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                try:
                    raw_args = tc["function"].get("arguments", "{}")
                    arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    arguments = {}

                logger.info(f"   ▶ 调用工具: {tool_name}  参数: {arguments}")
                try:
                    tool_result = await tool_registry.execute_tool(tool_name, arguments)
                    tool_output = str(tool_result.content) if hasattr(tool_result, "content") else str(tool_result)
                    logger.info(f"   ✅ 工具 [{tool_name}] 返回: {tool_output[:120]}")
                except Exception as e:
                    tool_output = f"工具调用失败: {e}"
                    logger.error(f"   ❌ 工具 [{tool_name}] 失败: {e}")

                collected_tool_calls.append(ToolCall(
                    task_id=task_id,
                    tool_name=tool_name,
                    arguments=json.dumps(arguments, ensure_ascii=False),
                    output=tool_output[:400],
                ))
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_output,
                })
        else:
            # for 循环正常耗尽（未 break），说明超过了最大轮数
            task.status = "failed"
            task.error = f"超过最大工具调用轮数 ({MAX_TOOL_ROUNDS})，任务未能完成"
            logger.error(f"❌ [Worker] 任务 {task_id} 超过最大轮数，标记为失败")
            return {"tasks": {task_id: task}, "current_task_id": task_id}

        if not task.result or not task.result.strip():
            task.status = "failed"
            task.error = "模型返回空内容，任务未能完成"
            logger.error(f"❌ [Worker] 任务 {task_id} 模型返回空内容，标记为失败")
            return {"tasks": {task_id: task}, "current_task_id": task_id}

        task.status = "completed"
        logger.info(f"✅ [Worker] 任务 {task_id} 执行完成，结果: {str(task.result)[:120]}")
        return {
            "tasks": {task_id: task},
            "tool_history": collected_tool_calls,
            "task_results": {task_id: task.result or ""},
            "current_task_id": task_id,
        }
    except Exception as e:
        task.status = "failed"
        task.error = str(e)
        logger.error(f"❌ [Worker] 执行任务 {task_id} 失败: {e}", exc_info=True)
        return {"tasks": {task_id: task}, "current_task_id": task_id}
