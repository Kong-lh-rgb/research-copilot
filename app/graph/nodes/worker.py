import asyncio
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
# 单个工具调用的超时时间（秒）
TOOL_CALL_TIMEOUT = 30
# 单次 LLM 调用的超时时间（秒）
LLM_CALL_TIMEOUT = 180
# 传给 LLM 的工具输出最大长度（字符）
MAX_TOOL_OUTPUT_TO_LLM = 3000


def _build_conversation_history(state: AgentState, max_messages: int = 5) -> str:
    """从 AgentState.messages 中提取近期对话历史（排除本轮用户消息），
    格式化为 Worker 可读的文本，让 Worker 能引用上一轮的分析结果。
    优化：减少历史消息数量以加快处理速度。"""
    messages = state.get("messages") or []
    # messages 最后一条是本轮用户输入，排除它
    history = messages[:-1] if messages else []
    # 只取最近 max_messages 条（减少到 5 条以提升速度）
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
        # 截断超长内容（减少到 1000 字符）
        snippet = content[:1000] + ("…" if len(content) > 1000 else "")
        lines.append(f"[{role_label}]: {snippet}")
    return "\n".join(lines)


async def worker_node(state: AgentState) -> dict:
    tasks = state.get("tasks", {})
    task_id = state.get("current_task_id", "")
    
    # 调试日志：输出接收到的状态
    logger.debug(f"[Worker] 接收状态: task_id={task_id}, tasks_keys={list(tasks.keys())}")
    
    if not task_id or task_id not in tasks:
        logger.error(f"❌ [Worker] 当前任务ID无效或不存在: {task_id}, 可用任务: {list(tasks.keys())}")
        return state  # 返回原状态，避免破坏状态结构
    
    task = tasks.get(task_id)
    
    # 如果任务已经是 running 或 completed，跳过
    if task.status == "completed":
        logger.info(f"⏭️ [Worker] 任务 {task_id} 已完成，跳过")
        return state
    
    # 标记任务为 running
    if task.status == "pending":
        task.status = "running"
        logger.info(f"🏃 [Worker] 任务 {task_id} 开始执行")
    
    if task.status != "running":
        logger.warning(f"⚠️ [Worker] 任务 {task_id} 状态异常: {task.status}")
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
            logger.info(f"🔄 [Worker] 任务 {task_id} 第 {round_idx + 1}/{MAX_TOOL_ROUNDS} 轮开始")
            
            # 添加 LLM 调用超时保护
            try:
                logger.debug(f"💭 [Worker] 等待 LLM 响应... (最长 {LLM_CALL_TIMEOUT}s)")
                result = await asyncio.wait_for(
                    call_llm(
                        messages=messages,
                        system=system,
                        tools=openai_tools if openai_tools else None,
                        temperature=0.1,
                    ),
                    timeout=LLM_CALL_TIMEOUT
                )
            except asyncio.TimeoutError:
                error_msg = f"LLM调用超时（{LLM_CALL_TIMEOUT}秒）"
                logger.error(f"⏱️ [Worker] 任务 {task_id} 第 {round_idx + 1} 轮 - {error_msg}")
                raise ValueError(error_msg)
            
            if result.get("error"):
                raise ValueError(result["error"])

            tool_calls = result.get("tool_calls")

            if not tool_calls:
                task.result = result.get("content", "")
                logger.info(f"✅ [Worker] 任务 {task_id} 第 {round_idx + 1} 轮完成，无需调用工具")
                break

            logger.info(f"🔧 [Worker] 第 {round_idx + 1} 轮，LLM 请求调用 {len(tool_calls)} 个工具")

            messages.append({
                "role": "assistant",
                "content": result.get("content") or "",
                "tool_calls": tool_calls,
            })

            # ⚡ 并行执行所有工具调用（性能优化）
            async def execute_single_tool(tc):
                """单个工具调用的包装函数，支持超时和错误处理"""
                tool_name = tc["function"]["name"]
                try:
                    raw_args = tc["function"].get("arguments", "{}")
                    arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    arguments = {}

                logger.info(f"   ▶ 调用工具: {tool_name}  参数: {arguments}")
                try:
                    # 添加超时控制，避免单个工具卡住太久
                    tool_result = await asyncio.wait_for(
                        tool_registry.execute_tool(tool_name, arguments),
                        timeout=TOOL_CALL_TIMEOUT
                    )
                    tool_output = str(tool_result.content) if hasattr(tool_result, "content") else str(tool_result)
                    logger.info(f"   ✅ 工具 [{tool_name}] 返回: {tool_output[:120]}")
                except asyncio.TimeoutError:
                    tool_output = f"工具调用超时（{TOOL_CALL_TIMEOUT}秒）"
                    logger.error(f"   ⏱️ 工具 [{tool_name}] 超时")
                except Exception as e:
                    tool_output = f"工具调用失败: {e}"
                    logger.error(f"   ❌ 工具 [{tool_name}] 失败: {e}")

                return {
                    "tc": tc,
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "output": tool_output
                }

            # 并行执行所有工具调用
            tool_results = await asyncio.gather(
                *[execute_single_tool(tc) for tc in tool_calls],
                return_exceptions=False
            )

            # 收集结果并构建消息
            for tr in tool_results:
                # 存储到 tool_history 时截断为 400 字符（用于日志/状态）
                collected_tool_calls.append(ToolCall(
                    task_id=task_id,
                    tool_name=tr["tool_name"],
                    arguments=json.dumps(tr["arguments"], ensure_ascii=False),
                    output=tr["output"][:400],
                ))
                
                # 🔧 关键修复：截断传给 LLM 的工具输出，避免上下文过长
                truncated_output = tr["output"][:MAX_TOOL_OUTPUT_TO_LLM]
                if len(tr["output"]) > MAX_TOOL_OUTPUT_TO_LLM:
                    truncated_output += f"\n\n[... 输出过长，已截断 {len(tr['output']) - MAX_TOOL_OUTPUT_TO_LLM} 字符 ...]"
                    logger.debug(f"✌️ 工具 [{tr['tool_name']}] 输出被截断: {len(tr['output'])} -> {MAX_TOOL_OUTPUT_TO_LLM}")
                
                messages.append({
                    "role": "tool",
                    "tool_call_id": tr["tc"]["id"],
                    "content": truncated_output,
                })
            
            logger.info(f"✅ [Worker] 任务 {task_id} 第 {round_idx + 1} 轮工具调用完成，准备下一轮 LLM 调用")
            # 循环会自动继续，LLM 会处理工具返回的结果
        else:
            # for 循环正常耗尽（未 break），说明超过了最大轮数
            task.status = "failed"
            task.error = f"超过最大工具调用轮数 ({MAX_TOOL_ROUNDS})，任务未能完成"
            logger.error(f"❌ [Worker] 任务 {task_id} 超过最大轮数，标记为失败")
            return {"current_task_id": task_id, "tasks": {task_id: task}}

        if not task.result or not task.result.strip():
            task.status = "failed"
            task.error = "模型返回空内容，任务未能完成"
            logger.error(f"❌ [Worker] 任务 {task_id} 模型返回空内容，标记为失败")
            return {"current_task_id": task_id, "tasks": {task_id: task}}

        task.status = "completed"
        logger.info(f"✅ [Worker] 任务 {task_id} 执行完成，结果: {str(task.result)[:120]}")
        return {
            "current_task_id": task_id,
            "tasks": {task_id: task},
            "tool_history": collected_tool_calls,
            "task_results": {task_id: task.result or ""},
        }
    except Exception as e:
        task.status = "failed"
        task.error = str(e)
        logger.error(f"❌ [Worker] 执行任务 {task_id} 失败: {e}", exc_info=True)
        return {"current_task_id": task_id, "tasks": {task_id: task}}
