import asyncio
import json
import logging
from typing import List
from langchain_core.runnables import RunnableConfig
from app.llm.wrapper import call_llm, call_llm_stream, mcp_tools_to_openai_tools
from app.graph.state import AgentState, ToolCall
from app.infrastructure.setup import tool_registry
from app.llm.prompt_manager import render

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5
TOOL_CALL_TIMEOUT = 30
LLM_CALL_TIMEOUT = 180
MAX_TOOL_OUTPUT_TO_LLM = 3000
HITL_TIMEOUT = 120  # seconds to wait for human approval

# 需要人工确认才能执行的敏感工具名称（不可逆/外部副作用操作）
SENSITIVE_TOOLS: set[str] = {
    "send_email",
    "send_wechat",
    "send_sms",
    "send_message",
    "create_order",
    "transfer_money",
}


def _missing_tool_names(tool_calls: list, available_tool_names: set[str]) -> list[str]:
    missing: list[str] = []
    for tc in tool_calls:
        name = tc.get("function", {}).get("name", "")
        if name and name not in available_tool_names and name not in missing:
            missing.append(name)
    return missing


def _compute_newly_ready(tasks: dict, completed_task_id: str) -> list:
    """返回因 completed_task_id 完成而被解锁的新就绪任务 ID 列表。

    只扫描依赖列表中包含 completed_task_id 的 pending 任务，
    复杂度 O(k·d)，k = pending 任务数，d = 平均依赖数，远优于全量扫描 O(n)。
    """
    newly_ready = []
    for tid, task in tasks.items():
        if task.status != "pending":
            continue
        if completed_task_id not in (task.dependencies or []):
            continue
        # 所有依赖均已完成才解锁
        if all(tasks.get(dep) and tasks[dep].status == "completed" for dep in task.dependencies):
            newly_ready.append(tid)
            logger.info(f"🔓 [Worker] 任务 [{tid}] 依赖已满足，加入 ready_tasks")
    return newly_ready


def _build_conversation_history(state: AgentState, max_messages: int = 5) -> str:
    messages = state.get("messages") or []
    history = messages[:-1] if messages else []
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
        # 截断超长内容（每条消息最多 3000 字符，保留更多上下文）
        snippet = content[:3000] + ("…" if len(content) > 3000 else "")
        lines.append(f"[{role_label}]: {snippet}")
    return "\n".join(lines)


async def worker_node(state: AgentState, config: RunnableConfig) -> dict:
    configurable = (config or {}).get("configurable", {})
    stream_queue = configurable.get("stream_queue")
    hitl_pending: dict = configurable.get("hitl_pending", {})
    hitl_thread_id: str = configurable.get("thread_id", "")

    tasks = state.get("tasks", {})
    task_id = state.get("current_task_id", "")
    
    # 调试日志：输出接收到的状态
    logger.debug(f"[Worker] 接收状态: task_id={task_id}, tasks_keys={list(tasks.keys())}")
    
    if not task_id or task_id not in tasks:
        logger.error(f"❌ [Worker] 当前任务ID无效或不存在: {task_id}, 可用任务: {list(tasks.keys())}")
        return {}  # 什么都不更新，避免干扰 add_int 计数器
    
    task = tasks.get(task_id)
    
    # 如果任务已经是 running 或 completed，跳过
    if task.status == "completed":
        logger.info(f"⏭️ [Worker] 任务 {task_id} 已完成，跳过")
        return {}
    
    # 标记任务为 running
    if task.status == "pending":
        task.status = "running"
        logger.info(f"🏃 [Worker] 任务 {task_id} 开始执行")
    
    if task.status != "running":
        logger.warning(f"⚠️ [Worker] 任务 {task_id} 状态异常: {task.status}")
        return {}
        
    try:
        user_input = state.get("user_input", "未提供")
        conversation_history = _build_conversation_history(state)

        
        dependencies_context = ""
        # 先加入明确声明的依赖任务结果
        declared_deps = set(task.dependencies or [])
        if declared_deps:
            for dep_id in task.dependencies:
                dep_task = tasks.get(dep_id)
                if dep_task and dep_task.result:
                    dependencies_context += f"【前置任务 {dep_id} - {dep_task.description}】的结果如下：\n{dep_task.result}\n\n"

        # 无论是否有声明依赖，把 state 里所有已完成任务的结果也补充进来
        # 这样续轮请求（如用户补充了邮箱）仍能看到上一轮的分析成果
        for tid, t in tasks.items():
            if tid in declared_deps:
                continue  # 已加过，跳过
            if t.status == "completed" and t.result and tid != task_id:
                dependencies_context += f"【已完成任务 {tid} - {t.description}】的结果如下：\n{t.result}\n\n"

        if not dependencies_context:
            dependencies_context = "无"

        all_tools = await tool_registry.get_all_tools()
        openai_tools = mcp_tools_to_openai_tools(all_tools)
        available_tool_names = {
            t.get("function", {}).get("name", "")
            for t in openai_tools
            if t.get("function", {}).get("name")
        }
        logger.info(f"🛠️ [Worker] 可用工具: {sorted(available_tool_names)}")

        system = render(
            "worker",
            conversation_history=conversation_history,
            user_input=user_input,
            dependencies_context=dependencies_context,
            task_id=task.task_id,
            task_description=task.description,
            available_tools=sorted(available_tool_names),
        )

        messages = [{"role": "user", "content": task.description}]
        collected_tool_calls: List[ToolCall] = []

        # for...else：只有 break（即 not tool_calls）才会跳过 else 块
        for round_idx in range(MAX_TOOL_ROUNDS):
            logger.info(f"🔄 [Worker] 任务 {task_id} 第 {round_idx + 1}/{MAX_TOOL_ROUNDS} 轮开始")
            
            # 添加 LLM 调用超时保护
            try:
                logger.debug(f"💭 [Worker] 等待 LLM 响应... (最长 {LLM_CALL_TIMEOUT}s)")
                full_content = ""
                tool_calls = None
                error_msg = None
                
                async def stream_and_collect():
                    nonlocal full_content, tool_calls, error_msg
                    try:
                        async for chunk in call_llm_stream(
                            messages=messages,
                            system=system,
                            tools=openai_tools if openai_tools else None,
                            temperature=0.1,
                            role="worker",
                        ):
                            if chunk.get("done"):
                                tool_calls = chunk.get("tool_calls")
                                if chunk.get("error"):
                                    error_msg = chunk.get("error")
                                break
                            
                            c = chunk.get("content", "")
                            t = chunk.get("thinking", "")
                            if c:
                                full_content += c
                                if stream_queue:
                                    # 用 thinking_token 传出，以和最终生成的 content_token 区分
                                    stream_queue.put_nowait({"type": "thinking_token", "delta": c})
                                    await asyncio.sleep(0)
                            if t:
                                if stream_queue:
                                    stream_queue.put_nowait({"type": "thinking_token", "delta": t})
                                    await asyncio.sleep(0)
                    except Exception as e:
                        error_msg = str(e)
                
                await asyncio.wait_for(stream_and_collect(), timeout=LLM_CALL_TIMEOUT)
                
                if error_msg:
                    raise ValueError(error_msg)
                
                result = {"content": full_content, "tool_calls": tool_calls}
                
            except asyncio.TimeoutError:
                error_msg = f"LLM调用超时（{LLM_CALL_TIMEOUT}秒）"
                logger.error(f"⏱️ [Worker] 任务 {task_id} 第 {round_idx + 1} 轮 - {error_msg}")
                raise ValueError(error_msg)
            
            if result.get("error"):
                raise ValueError(result["error"])

            tool_calls = result.get("tool_calls")

            if not tool_calls:
                # ── 检测特殊控制信号 ─────────────────────────────────────────
                raw_content = (result.get("content") or "").strip()
                if raw_content:
                    try:
                        import re as _re
                        # 兼容 LLM 在 content 外面包了 markdown 代码块的情况
                        json_str = _re.sub(r"^```[\w]*\n?", "", raw_content)
                        json_str = _re.sub(r"\n?```$", "", json_str).strip()
                        # 只取第一个 JSON 对象，防止前后有多余文字
                        m = _re.search(r"\{[\s\S]*\}", json_str)
                        if m:
                            signal = json.loads(m.group(0))

                            # ── cannot_complete：工具未接入 或 缺少必要用户信息，挂起等待输入 ──
                            if signal.get("cannot_complete"):
                                reason = signal.get("reason", "需要用户信息补充")
                                task.status = "suspended"
                                task.error = reason
                                logger.error(
                                    f"⏸️ [Worker] 任务 {task_id} 主动挂起，等待用户补充信息: {reason}"
                                )
                                return {
                                    "current_task_id": task_id,
                                    "tasks": {task_id: task},
                                    "tool_history": collected_tool_calls,
                                    "messages": [{"role": "assistant", "content": f"任务挂起需要补充信息：\n{reason}"}],
                                    "final_report": f"为了继续完成任务，我需要您补充以下信息：\n{reason}",
                                }

                    except (json.JSONDecodeError, ValueError):
                        pass  # 正常文本内容，不是信号
                # ── 正常完成 ─────────────────────────────────────────────────
                task.result = raw_content
                logger.info(f"✅ [Worker] 任务 {task_id} 第 {round_idx + 1} 轮完成，无需调用工具")
                break

            missing_tools = _missing_tool_names(tool_calls, available_tool_names)
            if missing_tools:
                available = sorted(available_tool_names)
                task.status = "failed"
                task.error = (
                    "任务无法继续：缺少所需工具 "
                    f"{', '.join(missing_tools)}。"
                    f"当前可用工具：{', '.join(available) if available else '无'}。"
                    "请检查 mcp_servers.json 配置、MCP 服务启动状态或工具名称是否正确。"
                )
                logger.error(
                    f"❌ [Worker] 任务 {task_id} 请求了不可用工具: {missing_tools}; "
                    f"可用工具: {available}"
                )
                return {
                    "current_task_id": task_id,
                    "tasks": {task_id: task},
                    "tool_history": collected_tool_calls,
                }

            logger.info(f"🔧 [Worker] 第 {round_idx + 1} 轮，LLM 请求调用 {len(tool_calls)} 个工具")

            messages.append({
                "role": "assistant",
                "content": result.get("content") or "",
                "tool_calls": tool_calls,
            })

            # ── Human-in-the-Loop：敏感工具执行前请求人工确认 ──────────────
            sensitive_in_round = [
                tc for tc in tool_calls
                if tc.get("function", {}).get("name", "") in SENSITIVE_TOOLS
            ]
            if sensitive_in_round and hitl_thread_id:
                # 取第一个敏感工具的信息（通常每轮只有一个）
                first = sensitive_in_round[0]
                s_name = first["function"]["name"]
                s_args = first["function"].get("arguments", "{}")
                description = f"即将执行 {len(sensitive_in_round)} 个敏感操作：" + \
                              "、".join(tc["function"]["name"] for tc in sensitive_in_round)

                logger.warning(
                    f"⏸️ [Worker] 任务 {task_id} 触发 HITL，等待用户确认: {s_name}"
                )
                if stream_queue:
                    stream_queue.put_nowait({
                        "type": "hitl_request",
                        "task_id": task_id,
                        "tool_name": s_name,
                        "arguments": s_args,
                        "description": description,
                    })

                loop = asyncio.get_event_loop()
                future: asyncio.Future = loop.create_future()
                hitl_pending[hitl_thread_id] = future

                try:
                    approved = await asyncio.wait_for(
                        asyncio.shield(future), timeout=HITL_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    hitl_pending.pop(hitl_thread_id, None)
                    task.status = "failed"
                    task.error = f"等待用户确认超时（{HITL_TIMEOUT}秒），任务已取消"
                    logger.error(f"⏱️ [Worker] HITL 超时，任务 {task_id} 取消")
                    return {"current_task_id": task_id, "tasks": {task_id: task}, "tool_history": collected_tool_calls}

                if not approved:
                    task.status = "failed"
                    task.error = "用户取消了操作，任务未执行"
                    logger.info(f"🚫 [Worker] 任务 {task_id} 被用户取消")
                    return {"current_task_id": task_id, "tasks": {task_id: task}, "tool_history": collected_tool_calls}

                logger.info(f"✅ [Worker] 用户确认，继续执行任务 {task_id}")
            # ── End HITL ─────────────────────────────────────────────────────

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
        newly_ready = _compute_newly_ready(tasks, task_id)
        return {
            "current_task_id": task_id,
            "tasks": {task_id: task},
            "tool_history": collected_tool_calls,
            "task_results": {task_id: task.result or ""},
            "ready_tasks": newly_ready,   # 解锁的下游任务
        }
    except Exception as e:
        task.status = "failed"
        task.error = str(e)
        logger.error(f"❌ [Worker] 执行任务 {task_id} 失败: {e}", exc_info=True)
        return {"current_task_id": task_id, "tasks": {task_id: task}}
