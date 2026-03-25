import asyncio
import json
import logging
import os
from typing import AsyncGenerator, Optional
from uuid import uuid4
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from app.services.chat_explainability import build_tool_evidence_summary
from app.services.chat_persistence import extract_user_id_from_token, save_turn_to_db, load_thread_history, load_task_state, save_task_state, clear_task_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    query: str
    thread_id: Optional[str] = None


def _format_message(msg_type: str, **kwargs) -> str:
    """将消息转化为 SSE 格式（每行一个 JSON）。"""
    payload = {"type": msg_type}
    if msg_type == "start" and "query" in kwargs:
        payload.update({"query": kwargs["query"], "thread_id": kwargs.get("thread_id")})
    elif msg_type == "log":
        payload.update({"message": kwargs.get("message", ""), "level": kwargs.get("level", "info")})
    elif msg_type == "task_start":
        payload.update({"task_id": kwargs.get("task_id", ""), "description": kwargs.get("description", "")})
    elif msg_type == "task_running":
        payload["task_id"] = kwargs.get("task_id", "")
    elif msg_type == "tool_call":
        payload.update({"tool_name": kwargs.get("tool_name", ""), "arguments": kwargs.get("arguments", "{}")})
    elif msg_type == "tool_result":
        payload.update({"tool_name": kwargs.get("tool_name", ""), "result": kwargs.get("result", "")})
    elif msg_type == "task_complete":
        payload["task_id"] = kwargs.get("task_id", "")
    elif msg_type == "hitl_request":
        payload.update({
            "task_id": kwargs.get("task_id", ""),
            "tool_name": kwargs.get("tool_name", ""),
            "arguments": kwargs.get("arguments", "{}"),
            "description": kwargs.get("description", ""),
        })
    elif msg_type in ("thinking_token", "content_token"):
        payload["delta"] = kwargs.get("delta", "")
    elif msg_type == "final":
        payload["reply"] = kwargs.get("reply", "")
    elif msg_type == "error":
        payload["message"] = kwargs.get("message", "")
    return json.dumps(payload, ensure_ascii=False)


async def _stream_chat_response(
    request: Request,
    compiled_graph,
    query: str,
    thread_id: str,
    query_id: str,
    reply_holder: Optional[list] = None,
    trace_user_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    queue: asyncio.Queue = asyncio.Queue()
    request.app.state.stream_queues[thread_id] = queue

    try:
        yield _format_message("start", query=query, thread_id=thread_id)
        
        # ── 初始 Log ──────────────────────────────────────────────────────────
        queue.put_nowait({"type": "log", "message": "🤔 解析用户意图...", "level": "info"})

        # ── 加载历史消息（上文记忆）─────────────────────────────────────────
        history = await load_thread_history(thread_id)
        
        # ── 加载之前保存的任务状态（用于恢复挂起任务）──────────────────────
        persisted_tasks = load_task_state(thread_id)
        logger.info(f"[Chat] 已加载保存的任务状态: 共 {len(persisted_tasks)} 个任务")
        for tid, t in persisted_tasks.items():
            status = getattr(t, "status", "?")
            logger.info(f"[Chat]   - {tid}: {status}")

        turn_state = {
            "messages": history + [{"id": query_id, "role": "user", "content": query}],
            "user_input": query,
            "thread_id": thread_id,
            "tasks": persisted_tasks or {},  # 如果有保存的任务状态则恢复，否则为空
            "next_action": "",
            "tool_history": [],
            "task_results": {},
        }

        final_reply = ""
        task_display = {}
        # 记录已推送出的工具调用索引，防止重复推送
        emitted_tool_indices = set()
        collected_tool_calls_for_evidence: list[dict] = []
        evidence_signatures: set[str] = set()
        graph_done = asyncio.Event()

        async def _run_graph():
            nonlocal final_reply, turn_state
            try:
                # 监听 LangGraph 每一个步骤
                async for step in compiled_graph.astream(
                    turn_state,
                    config={
                        "run_name": "chat_stream_turn",
                        "tags": ["api:chat", "stream", f"thread:{thread_id}"],
                        "metadata": {
                            "thread_id": thread_id,
                            "has_auth_user": bool(trace_user_id),
                            "user_id": trace_user_id,
                            "query_len": len(query or ""),
                        },
                        "configurable": {
                            "thread_id": thread_id,
                            "stream_queue": queue,
                            "hitl_pending": request.app.state.hitl_pending,
                        },
                    },
                ):
                    for node_name, node_output in step.items():
                        if node_name == "__start__":
                            continue
                        if not isinstance(node_output, dict):
                            continue
                        
                        # ⚠️ 关键：每步后更新 turn_state，确保保存最新的任务状态
                        if "tasks" in node_output:
                            turn_state["tasks"] = node_output.get("tasks", turn_state.get("tasks", {}))
                        if node_name == "controller":
                            if "next_action" in node_output:
                                action = node_output["next_action"]
                                queue.put_nowait({"type": "log", "message": f"✓ 意图: {action}", "level": "success"})
                                if action == "complex_research":
                                    queue.put_nowait({"type": "log", "message": "📋 正在规划子任务...", "level": "info"})

                        elif node_name == "planner":
                            tasks = node_output.get("tasks", {})
                            if tasks:
                                queue.put_nowait({"type": "log", "message": f"📊 已规划 {len(tasks)} 个子任务", "level": "info"})
                                for task_id, task_node in tasks.items():
                                    task_display[task_id] = {"description": task_node.description, "status": "pending"}
                                    queue.put_nowait({"type": "task_start", "task_id": task_id, "description": task_node.description})

                        elif node_name == "worker":
                            current_task_id = node_output.get("current_task_id", "")
                            
                            if "final_report" in node_output:
                                final_reply = node_output["final_report"]
                                
                            # 工具调用去重推送
                            tool_history = node_output.get("tool_history", [])
                            for idx, tool_call in enumerate(tool_history):
                                if idx in emitted_tool_indices:
                                    continue
                                emitted_tool_indices.add(idx)

                                signature = "|".join(
                                    [
                                        str(tool_call.get("task_id", "")),
                                        str(tool_call.get("tool_name", "")),
                                        str(tool_call.get("arguments", "")),
                                        str(tool_call.get("output", ""))[:200],
                                    ]
                                )
                                if signature not in evidence_signatures:
                                    evidence_signatures.add(signature)
                                    collected_tool_calls_for_evidence.append(
                                        {
                                            "task_id": tool_call.get("task_id", ""),
                                            "tool_name": tool_call.get("tool_name", ""),
                                            "arguments": tool_call.get("arguments", "{}"),
                                            "output": tool_call.get("output", ""),
                                        }
                                    )
                                
                                queue.put_nowait({"type": "tool_call", "tool_name": tool_call.get("tool_name", ""), "arguments": tool_call.get("arguments", "{}")})
                                queue.put_nowait({"type": "tool_result", "tool_name": tool_call.get("tool_name", ""), "result": tool_call.get("output", "")[:200]})

                            # 根据 tasks 中的实际状态更新前端
                            if current_task_id:
                                tasks_update = node_output.get("tasks", {})
                                if current_task_id in tasks_update:
                                    task_node = tasks_update[current_task_id]
                                    new_status = task_node.status
                                    
                                    # 只在状态变化时推送更新
                                    if current_task_id not in task_display or task_display[current_task_id]["status"] != new_status:
                                        task_display[current_task_id] = {"description": task_node.description, "status": new_status}
                                        
                                        if new_status == "running":
                                            queue.put_nowait({"type": "task_running", "task_id": current_task_id})
                                        elif new_status == "completed":
                                            queue.put_nowait({"type": "task_complete", "task_id": current_task_id})
                                        elif new_status == "suspended":
                                            error_message = task_node.error or "需要补充信息"
                                            queue.put_nowait({"type": "task_failed", "task_id": current_task_id, "error": error_message})
                                            queue.put_nowait({
                                                "type": "log",
                                                "message": f"⏸️ 子任务 {current_task_id} 挂起等待输入：{error_message}",
                                                "level": "warning",
                                            })
                                        elif new_status == "failed":
                                            error_message = task_node.error or "未知错误"
                                            queue.put_nowait({"type": "task_failed", "task_id": current_task_id, "error": error_message})
                                            queue.put_nowait({
                                                "type": "log",
                                                "message": f"❌ 子任务 {current_task_id} 执行失败：{error_message}",
                                                "level": "error",
                                            })

                        elif node_name == "reviewer":
                            # 汇总时推 log
                            queue.put_nowait({"type": "log", "message": "✍️ 正在汇总最终结果...", "level": "info"})
                            if "final_report" in node_output:
                                final_reply = node_output["final_report"]

                        elif node_name == "simple_chat":
                            if "final_report" in node_output:
                                final_reply = node_output["final_report"]

            except Exception as e:
                logger.error(f"Graph run error: {e}", exc_info=True)
                queue.put_nowait({"type": "error", "message": f"执行出错: {str(e)}"})
            finally:
                # 保存任务状态，以便用户补充信息后恢复
                if turn_state and "tasks" in turn_state:
                    save_task_state(thread_id, turn_state["tasks"])
                graph_done.set()

        async def _drain():
            while True:
                # 使用阻塞式 get（带超时），token 入队后立即被唤醒
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    # 超时检查退出条件
                    if graph_done.is_set() and queue.empty():
                        break
                    if await request.is_disconnected():
                        logger.warning(f"⚠️ [Chat] 检测到客户端已主动断开 (线程 {thread_id})")
                        break
                    continue

                if item is None:
                    continue
                if await request.is_disconnected():
                    break
                # ⚠️ 返回纯 JSON，不添加 SSE 前缀（统一由外层 generate() 处理）
                yield json.dumps(item, ensure_ascii=False)
                # 让事件循环有机会把 HTTP 写缓冲区刷新到网络，
                # 避免多个 token 被 TCP 打包成一次发送
                await asyncio.sleep(0)

        # 运行图并分发事件
        graph_task = asyncio.create_task(_run_graph())

        try:
            async for raw_json in _drain():
                yield raw_json
        finally:
            if not graph_task.done():
                logger.warning(f"🛑 [Chat] 客户端已断开，停止后台任务，同时保存当前任务状态...")
                # ⚠️ 关键：在 cancel 前立即保存任务状态
                if turn_state and "tasks" in turn_state:
                    save_task_state(thread_id, turn_state["tasks"])
                    logger.info(f"💾 [Chat] 任务状态已在 cancel 前保存 (thread={thread_id})")
                
                graph_task.cancel()
                try:
                    await graph_task
                except asyncio.CancelledError:
                    pass

        if not graph_task.cancelled():
            try:
                await graph_task
            except asyncio.CancelledError:
                pass

        # 只有在最终没有 content_token 推送内容时，才做 final 兜底（由前端保证不重复渲染）
        if final_reply:
            evidence_summary = build_tool_evidence_summary(collected_tool_calls_for_evidence)
            if evidence_summary and "## 引用来源 / 工具证据摘要" not in final_reply:
                final_reply = final_reply + evidence_summary

            if reply_holder is not None:
                reply_holder.append(final_reply)
            yield _format_message("log", message="✅ 执行完毕", level="success")
            yield _format_message("final", reply=final_reply)

        yield _format_message("end")

    except Exception as e:
        logger.error(f"Chat stream error: {e}", exc_info=True)
        yield _format_message("error", message=str(e))
    finally:
        request.app.state.stream_queues.pop(thread_id, None)


@router.post("/stream")
async def chat_stream(request: Request, body: ChatRequest):
    from fastapi.responses import StreamingResponse

    # ── 邀请码校验 ─────────────────────────────────────────────────────────────
    access_code = os.environ.get("ACCESS_CODE", "").strip()
    if access_code:
        provided = request.headers.get("X-Access-Code", "").strip()
        if provided != access_code:
            return JSONResponse(
                status_code=403,
                content={"detail": "邀请码错误或未提供，请在设置中填写正确的邀请码。"},
            )

    compiled_graph = request.app.state.compiled_graph
    thread_id = body.thread_id or f"web_{uuid4().hex}"
    
    # 防止并发写入产生 Checkpoint 数据错乱和 Queue 覆盖
    if thread_id in request.app.state.stream_queues:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=409,
            detail="当前对话正在处理中，请等待完成后再发送新消息。"
        )
    
    query_id = f"query_{uuid4().hex}"

    # Extract optional Bearer token for per-user message persistence
    auth_header = request.headers.get("Authorization", "")
    token: Optional[str] = (
        auth_header.removeprefix("Bearer ").strip()
        if auth_header.startswith("Bearer ")
        else None
    )
    trace_user_id = extract_user_id_from_token(token)

    async def generate():
        reply_holder: list[str] = []
        async for message in _stream_chat_response(
            request,
            compiled_graph,
            body.query,
            thread_id,
            query_id,
            reply_holder,
            trace_user_id,
        ):
            yield f"data: {message}\n\n"

        # Persist user query + assistant reply to PostgreSQL when authenticated
        if token:
            final_reply = reply_holder[0] if reply_holder else ""
            try:
                await save_turn_to_db(token, thread_id, body.query, final_reply)
            except Exception as e:
                logger.warning(f"Failed to persist turn to DB: {e}")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class HitlConfirmRequest(BaseModel):
    approved: bool


@router.post("/confirm/{thread_id}")
async def hitl_confirm(thread_id: str, body: HitlConfirmRequest, request: Request):
    """Human-in-the-Loop 确认端点：前端用户点击"确认/取消"后调用此接口。"""
    hitl_pending: dict = request.app.state.hitl_pending
    future: asyncio.Future = hitl_pending.get(thread_id)
    if future is None or future.done():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="没有等待确认的操作，可能已超时或已处理。")
    future.set_result(body.approved)
    hitl_pending.pop(thread_id, None)
    action = "批准" if body.approved else "取消"
    logger.info(f"✅ [HITL] thread={thread_id} 操作已{action}")
    return {"status": "ok", "approved": body.approved}
