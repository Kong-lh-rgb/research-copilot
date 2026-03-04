from typing import Any, Dict, List, Optional

from app.llm.client import get_llm


def call_llm(
    messages: List[Dict[str, Any]],
    system: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    temperature: float = 0,
) -> Dict[str, Any]:
    client = get_llm()

    request_messages = messages
    if system:
        request_messages = [{"role": "system", "content": system}] + messages

    try:
        response = client.chat(
            messages=request_messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
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
