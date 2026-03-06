import json
import logging
from typing import AsyncGenerator, Optional
from uuid import uuid4
from fastapi import APIRouter
from pydantic import BaseModel

from app.graph.build_graph import build_graph
from app.infrastructure.setup import tool_registry
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    query: str
    thread_id: Optional[str] = None


def _format_message(msg_type: str, **kwargs) -> str:
    """将消息转化为 SSE 格式（每行一个 JSON）。
    
    事件类型及字段：
    - start: query
    - log: message, level ("info", "success", "warning", "error")
    - task_start: task_id, description
    - task_running: task_id
    - tool_call: tool_name, arguments（JSON字符串）
    - tool_result: tool_name, result
    - task_complete: task_id
    - final: reply（完整的markdown文本）
    - error: message
    - end: （无额外字段）
    """
    payload = {"type": msg_type}
    
    # 根据事件类型添加相应字段
    if msg_type == "start" and "query" in kwargs:
        payload["query"] = kwargs["query"]
        if "thread_id" in kwargs and kwargs["thread_id"]:
            payload["thread_id"] = kwargs["thread_id"]
    elif msg_type == "log":
        payload["message"] = kwargs.get("message", "")
        payload["level"] = kwargs.get("level", "info")
    elif msg_type == "task_start":
        payload["task_id"] = kwargs.get("task_id", "")
        payload["description"] = kwargs.get("description", "")
    elif msg_type == "task_running":
        payload["task_id"] = kwargs.get("task_id", "")
    elif msg_type == "tool_call":
        payload["tool_name"] = kwargs.get("tool_name", "")
        payload["arguments"] = kwargs.get("arguments", "{}")
    elif msg_type == "tool_result":
        payload["tool_name"] = kwargs.get("tool_name", "")
        payload["result"] = kwargs.get("result", "")
    elif msg_type == "task_complete":
        payload["task_id"] = kwargs.get("task_id", "")
    elif msg_type == "final":
        payload["reply"] = kwargs.get("reply", "")
    elif msg_type == "error":
        payload["message"] = kwargs.get("message", "")
    
    return json.dumps(payload, ensure_ascii=False)


async def _stream_chat_response(query: str, thread_id: str) -> AsyncGenerator[str, None]:
    """流式处理聊天请求，产生结构化事件流。

    事件类型：
    - start: 开始处理
    - log: 执行日志（浅色显示）
    - task_start: 任务开始
    - task_running: 任务运行中
    - tool_call: 工具调用
    - tool_result: 工具结果
    - task_complete: 任务完成
    - final: 最终回复（重色显示）
    - error: 错误
    - end: 处理完成
    """
    try:
        yield _format_message("start", query=query, thread_id=thread_id)
        
        async with AsyncSqliteSaver.from_conn_string("memory.db") as checkpointer:
            app = build_graph().compile(checkpointer=checkpointer)
            
            turn_state = {
                "messages": [{"role": "user", "content": query}],
                "user_input": query,
                "tasks": {},
                "next_action": "",
                "tool_history": [],
                "task_results": {},
                "observations": {},
            }
            
            final_reply = ""
            task_display = {}  # 缓存任务信息用于前端显示
            emitted_tool_keys = set()
            
            async for step in app.astream(
                turn_state,
                config={"configurable": {"thread_id": thread_id}}
            ):
                # step 是 {node_name: node_output} 的字典
                for node_name, node_output in step.items():
                    if node_name == "__start__":
                        continue
                    
                    if not isinstance(node_output, dict):
                        continue
                    
                    # ── 意图识别节点 ──
                    if node_name == "controller":
                        yield _format_message("log", message="🤔 分析用户意图...", level="info")
                        if "next_action" in node_output:
                            action = node_output["next_action"]
                            yield _format_message("log", message=f"✓ 意图: {action}", level="success")
                    
                    # ── 任务规划节点 ──
                    elif node_name == "planner":
                        tasks = node_output.get("tasks", {})
                        if tasks:
                            yield _format_message("log", message=f"📋 规划 {len(tasks)} 个任务", level="info")
                            for task_id, task_node in tasks.items():
                                task_display[task_id] = {
                                    "description": task_node.description,
                                    "status": "pending",
                                }
                                yield _format_message("task_start", task_id=task_id, description=task_node.description)
                    
                    # ── 工具执行节点（关键） ──
                    elif node_name == "worker":
                        current_task_id = node_output.get("current_task_id", turn_state.get("current_task_id", ""))
                        if current_task_id in task_display:
                            task_display[current_task_id]["status"] = "running"
                            yield _format_message("task_running", task_id=current_task_id)
                        
                        # 推送工具调用历史
                        tool_history = node_output.get("tool_history", [])
                        for tool_call in tool_history:
                            tool_name = tool_call.get("tool_name", "Unknown")
                            arguments = tool_call.get("arguments", "{}")
                            output = tool_call.get("output", "")[:100]
                            key = f"{tool_call.get('task_id', '')}:{tool_name}:{arguments}:{output}"

                            if key in emitted_tool_keys:
                                continue
                            emitted_tool_keys.add(key)

                            yield _format_message("tool_call", tool_name=tool_name, arguments=arguments)
                            yield _format_message("tool_result", tool_name=tool_name, result=output)
                        
                        # 推送任务完成
                        if current_task_id in task_display:
                            task_display[current_task_id]["status"] = "completed"
                            yield _format_message("task_complete", task_id=current_task_id)
                    
                    # ── 结果汇总节点 ──
                    elif node_name == "reviewer":
                        yield _format_message("log", message="📊 汇总结果...", level="info")
                        if "final_report" in node_output:
                            final_reply = node_output["final_report"]
                    
                    # ── 直接回复节点 ──
                    elif node_name == "simple_chat":
                        yield _format_message("log", message="💬 生成回复...", level="info")
                        if "final_report" in node_output:
                            final_reply = node_output["final_report"]
            
            # 发送最终回复
            if final_reply:
                yield _format_message("log", message="✓ 生成完成", level="success")
                yield _format_message("final", reply=final_reply)
            else:
                yield _format_message("log", message="⚠️ 未生成回复", level="warning")
            
            yield _format_message("end")
        
    except Exception as e:
        logger.error(f"Chat stream error: {e}", exc_info=True)
        yield _format_message("error", message=str(e))


def _get_node_display_name(node_name: str) -> str:
    """把节点名转化为人类可读的步骤名。"""
    names = {
        "controller": "意图识别",
        "planner": "任务规划",
        "worker": "工具执行",
        "reviewer": "结果汇总",
        "simple_chat": "直接回复",
    }
    return names.get(node_name, node_name)


@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """
    流式聊天端点。
    
    前端连接此端点后，会收到 SSE 流，每行一个 JSON 消息：
    - {"type": "start", "query": "..."}
    - {"type": "node_step", "node": "...", "step_name": "...", "data": {...}}
    - {"type": "final", "reply": "..."}
    - {"type": "end"}
    """
    from fastapi.responses import StreamingResponse
    
    thread_id = request.thread_id or f"web_{uuid4().hex}"
    logger.info(f"New chat stream: query={request.query}, thread_id={thread_id}")

    async def generate():
        async for message in _stream_chat_response(request.query, thread_id):
            yield f"data: {message}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/health")
async def health_check():
    """健康检查端点。"""
    return {"status": "ok"}
