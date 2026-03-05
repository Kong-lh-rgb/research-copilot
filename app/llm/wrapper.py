from typing import Any, Dict, List, Optional

from app.llm.client import get_llm


async def call_llm(
    messages: List[Dict[str, Any]],
    system: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    temperature: float = 0,
    model: Optional[str] = None, # 传递自定义模型
) -> Dict[str, Any]:
    client = get_llm()

    request_messages = messages
    if system:
        request_messages = [{"role": "system", "content": system}] + messages

    # 空列表会让部分模型报错，统一转成 None
    effective_tools = tools if tools else None

    try:
        response = await client.chat(
            messages=request_messages,
            tools=effective_tools,
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

        return {
            "content": content,
            "tool_calls": tool_calls,
            "raw": response,
        }
    except Exception as e:
        return {
            "content": "",
            "tool_calls": None,
            "error": str(e),
        }

def mcp_tools_to_openai_tools(mcp_tools) -> List[Dict[str, Any]]:
    """将 MCP Tool 对象列表映射为 OpenAI function-calling tools 格式"""
    openai_tools = []
    for tool in mcp_tools:
        # MCP Tool 是 Pydantic 对象，用属性访问而非 dict.get()
        input_schema = getattr(tool, "inputSchema", None)
        if input_schema is None:
            input_schema = {"type": "object", "properties": {}}
        # Pydantic 对象需 model_dump()，普通 dict 直接用
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