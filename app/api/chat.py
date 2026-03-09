import asyncio
import json
import logging
import uuid as _uuid
from typing import AsyncGenerator, Optional
from uuid import uuid4
from fastapi import APIRouter, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


def _extract_user_id_from_token(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    try:
        from jose import jwt
        from app.api.auth import SECRET_KEY, ALGORITHM

        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str = payload.get("sub")
        return user_id_str if isinstance(user_id_str, str) else None
    except Exception:
        return None


def _build_tool_evidence_summary(tool_calls: list[dict], max_items: int = 8) -> str:
    if not tool_calls:
        return ""

    lines = ["\n\n---\n\n## 引用来源 / 工具证据摘要"]
    for idx, item in enumerate(tool_calls[:max_items], start=1):
        tool_name = str(item.get("tool_name", "")).strip() or "unknown_tool"
        raw_args = str(item.get("arguments", "")).strip() or "{}"
        raw_output = str(item.get("output", "")).replace("\n", " ").strip()
        output_excerpt = (raw_output[:140] + "…") if len(raw_output) > 140 else raw_output
        lines.append(f"{idx}. **{tool_name}**")
        lines.append(f"   - 参数：`{raw_args}`")
        lines.append(f"   - 证据摘录：{output_excerpt or '（无输出）'}")

    if len(tool_calls) > max_items:
        lines.append(f"\n> 其余 {len(tool_calls) - max_items} 条工具调用已省略。")

    return "\n".join(lines)


async def _save_turn_to_db(
    token: str,
    thread_id: str,
    user_query: str,
    assistant_reply: str,
) -> None:
    """Persist a user/assistant message pair to PostgreSQL after stream ends."""
    try:
        from jose import jwt, JWTError
        from app.api.auth import SECRET_KEY, ALGORITHM
        from app.db.session import get_session_factory
        from app.db import repository

        factory = get_session_factory()
        if factory is None:
            return

        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str: str | None = payload.get("sub")
        if not user_id_str:
            return

        user_id = _uuid.UUID(user_id_str)
        title = user_query[:30] if user_query else "新对话"

        async with factory() as session:
            await repository.get_or_create_thread(session, thread_id, user_id, title)
            await repository.add_message(session, thread_id, "user", user_query)
            if assistant_reply:
                await repository.add_message(session, thread_id, "assistant", assistant_reply)
            await repository.touch_thread(session, thread_id)
            await session.commit()

    except Exception as e:
        logger.warning(f"Failed to persist turn to DB: {e}")


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
    reply_holder: Optional[list] = None,
    trace_user_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    queue: asyncio.Queue = asyncio.Queue()
    request.app.state.stream_queues[thread_id] = queue

    try:
        yield _format_message("start", query=query, thread_id=thread_id)
        
        # ── 初始 Log ──────────────────────────────────────────────────────────
        queue.put_nowait({"type": "log", "message": "🤔 解析用户意图...", "level": "info"})

        turn_state = {
            "messages": [{"role": "user", "content": query}],
            "user_input": query,
            "thread_id": thread_id,
            "tasks": {},
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
            nonlocal final_reply
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
                        },
                    },
                ):
                    for node_name, node_output in step.items():
                        if node_name == "__start__":
                            continue
                        if not isinstance(node_output, dict):
                            continue

                        # ── 节点状态映射到 SSE 事件 ──
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
                                        elif new_status == "failed":
                                            queue.put_nowait({"type": "task_failed", "task_id": current_task_id, "error": task_node.error or "未知错误"})

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
                    continue

                if item is None:
                    continue
                # ⚠️ 返回纯 JSON，不添加 SSE 前缀（统一由外层 generate() 处理）
                yield json.dumps(item, ensure_ascii=False)
                # 让事件循环有机会把 HTTP 写缓冲区刷新到网络，
                # 避免多个 token 被 TCP 打包成一次发送
                await asyncio.sleep(0)

        # 运行图并分发事件
        graph_task = asyncio.create_task(_run_graph())

        async for raw_json in _drain():
            yield raw_json

        await graph_task

        # 只有在最终没有 content_token 推送内容时，才做 final 兜底（由前端保证不重复渲染）
        if final_reply:
            evidence_summary = _build_tool_evidence_summary(collected_tool_calls_for_evidence)
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
    compiled_graph = request.app.state.compiled_graph
    thread_id = body.thread_id or f"web_{uuid4().hex}"

    # Extract optional Bearer token for per-user message persistence
    auth_header = request.headers.get("Authorization", "")
    token: Optional[str] = (
        auth_header.removeprefix("Bearer ").strip()
        if auth_header.startswith("Bearer ")
        else None
    )
    trace_user_id = _extract_user_id_from_token(token)

    async def generate():
        reply_holder: list[str] = []
        async for message in _stream_chat_response(
            request,
            compiled_graph,
            body.query,
            thread_id,
            reply_holder,
            trace_user_id,
        ):
            yield f"data: {message}\n\n"

        # Persist user query + assistant reply to PostgreSQL when authenticated
        if token:
            final_reply = reply_holder[0] if reply_holder else ""
            await _save_turn_to_db(token, thread_id, body.query, final_reply)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
