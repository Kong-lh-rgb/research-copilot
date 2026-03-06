import asyncio
import json
import logging
from typing import AsyncGenerator, Optional
from uuid import uuid4
from fastapi import APIRouter, Request
from pydantic import BaseModel

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
    elif msg_type in ("thinking_token", "content_token"):
        payload["delta"] = kwargs.get("delta", "")
    elif msg_type == "final":
        payload["reply"] = kwargs.get("reply", "")
    elif msg_type == "error":
        payload["message"] = kwargs.get("message", "")
    return json.dumps(payload, ensure_ascii=False)


async def _stream_chat_response(
    request: Request, compiled_graph, query: str, thread_id: str
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
        graph_done = asyncio.Event()

        async def _run_graph():
            nonlocal final_reply
            try:
                # 监听 LangGraph 每一个步骤
                async for step in compiled_graph.astream(
                    turn_state,
                    config={"configurable": {"thread_id": thread_id}},
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
                            if current_task_id in task_display:
                                task_display[current_task_id]["status"] = "running"
                                queue.put_nowait({"type": "task_running", "task_id": current_task_id})

                            # 工具调用去重推送
                            tool_history = node_output.get("tool_history", [])
                            for idx, tool_call in enumerate(tool_history):
                                if idx in emitted_tool_indices:
                                    continue
                                emitted_tool_indices.add(idx)
                                
                                queue.put_nowait({"type": "tool_call", "tool_name": tool_call.get("tool_name", ""), "arguments": tool_call.get("arguments", "{}")})
                                queue.put_nowait({"type": "tool_result", "tool_name": tool_call.get("tool_name", ""), "result": tool_call.get("output", "")[:200]})

                            if current_task_id in task_display:
                                task_display[current_task_id]["status"] = "completed"
                                queue.put_nowait({"type": "task_complete", "task_id": current_task_id})

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
                # 使用阻塞式 get（带超时），token 入队后立即被唤醒，不再 10ms 轮询积压
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    # 超时检查退出条件
                    if graph_done.is_set() and queue.empty():
                        break
                    continue

                if item is None:
                    # None 是 sentinel，检查是否可以退出
                    if graph_done.is_set() and queue.empty():
                        break
                    continue
                yield json.dumps(item, ensure_ascii=False)

        # 运行图并分发事件
        graph_task = asyncio.create_task(_run_graph())

        async for raw_json in _drain():
            yield raw_json

        await graph_task

        # 只有在最终没有 content_token 推送内容时，才做 final 兜底（由前端保证不重复渲染）
        if final_reply:
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
    
    async def generate():
        async for message in _stream_chat_response(request, compiled_graph, body.query, thread_id):
            yield f"data: {message}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
