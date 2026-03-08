from typing import Any, AsyncGenerator, Dict, List, Optional

from app.llm.client import get_llm

#普通调用大模型的封装
async def call_llm(
    messages: List[Dict[str, Any]],
    system: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    temperature: float = 0,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    client = get_llm()

    request_messages = messages
    if system:
        request_messages = [{"role": "system", "content": system}] + messages

    try:
        response = await client.chat(
            messages=request_messages,
            tools=tools or None,
            tool_choice=tool_choice,
            temperature=temperature,
            model=model,
        )

        choices = response.get("choices", [])
        content = ""
        tool_calls = None
        if choices:
            message = (choices[0].get("message", {}) or {})
            content = message.get("content", "") or ""
            tool_calls = message.get("tool_calls")

        return {"content": content, "tool_calls": tool_calls}
    except Exception as e:
        return {"content": "", "tool_calls": None, "error": str(e)}

#流式调用大模型的封装
#注意：仅用于无工具调用的最终输出节点
async def call_llm_stream(
    messages: List[Dict[str, Any]],
    system: Optional[str] = None,
    temperature: float = 0,
    model: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """流式调用 LLM（仅用于无工具调用的最终输出节点）。

    每次 yield 一个 chunk：
    - {"thinking": "...", "content": "...", "done": False}  — 中间 token
    - {"thinking": "", "content": "", "done": True}         — 结束
    """
    client = get_llm()

    request_messages = messages
    if system:
        request_messages = [{"role": "system", "content": system}] + messages

    try:
        async for chunk in client.chat_stream(
            messages=request_messages,
            temperature=temperature,
            model=model,
        ):
            yield chunk
    except Exception as e:
        yield {"thinking": "", "content": "", "done": True, "error": str(e)}


def mcp_tools_to_openai_tools(mcp_tools) -> List[Dict[str, Any]]:
    """将 MCP Tool 对象列表映射为 OpenAI function-calling tools 格式"""
    openai_tools = []
    for tool in mcp_tools:
        input_schema = getattr(tool, "inputSchema", None)
        if input_schema is None:
            input_schema = {"type": "object", "properties": {}}
        if hasattr(input_schema, "model_dump"):
            input_schema = input_schema.model_dump(exclude_none=True)
        openai_tools.append({
            "type": "function",
            "function": {
                "name": getattr(tool, "name", ""),
                "description": getattr(tool, "description", "") or "",
                "parameters": input_schema,
            }
        })
    return openai_tools