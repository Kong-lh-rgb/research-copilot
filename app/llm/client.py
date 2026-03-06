import logging
import os
from functools import lru_cache
from typing import Any, AsyncGenerator, Dict, List, Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI

from app.shared.errors import LLMServiceError

load_dotenv()

# 阿里云 DashScope 不走系统代理（macOS 会自动读取系统代理，导致请求失败）
os.environ.setdefault("NO_PROXY", "aliyuncs.com,dashscope.aliyuncs.com")

logger = logging.getLogger(__name__)


class LLMConfigError(RuntimeError):
    pass


class LLMClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self._model = model or os.getenv("OPENAI_MODEL")

        if not self.api_key:
            raise LLMConfigError("未设置第三方模型API")

        self._client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url or None,
        )

    @property
    def model(self) -> str:
        return self._model

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        logger.debug("模型请求: %s", {"messages": messages, "tools": tools, "model": model or self._model})
        request_payload: Dict[str, Any] = {
            "model": model or self._model,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
        }
        if temperature is not None:
            request_payload["temperature"] = temperature

        try:
            resp = await self._client.chat.completions.create(**request_payload)
        except Exception as e:
            raise LLMServiceError(f"模型请求失败: {e}") from e

        logger.debug("模型响应: %s", getattr(resp, "id", ""))
        return resp.model_dump()

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, str], None]:
        """流式调用 LLM，逐 token yield {"thinking": str, "content": str, "done": bool}。"""
        request_payload: Dict[str, Any] = {
            "model": model or self._model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            request_payload["tools"] = tools
            request_payload["tool_choice"] = tool_choice or "auto"
        if temperature is not None:
            request_payload["temperature"] = temperature

        try:
            stream = await self._client.chat.completions.create(**request_payload)
        except Exception as e:
            raise LLMServiceError(f"模型流式请求失败: {e}") from e

        # 累积 tool_calls 以便最终返回
        accumulated_tool_calls: List[Dict[str, Any]] = []

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            finish_reason = chunk.choices[0].finish_reason

            # reasoning_content（Qwen-thinking 专属字段）
            thinking_delta = getattr(delta, "reasoning_content", None) or ""
            content_delta = delta.content or ""

            # 累积 tool_calls
            if delta.tool_calls:
                for tc_chunk in delta.tool_calls:
                    idx = tc_chunk.index
                    while len(accumulated_tool_calls) <= idx:
                        accumulated_tool_calls.append(
                            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                        )
                    slot = accumulated_tool_calls[idx]
                    if tc_chunk.id:
                        slot["id"] = tc_chunk.id
                    if tc_chunk.function:
                        if tc_chunk.function.name:
                            slot["function"]["name"] += tc_chunk.function.name
                        if tc_chunk.function.arguments:
                            slot["function"]["arguments"] += tc_chunk.function.arguments

            if thinking_delta or content_delta:
                yield {"thinking": thinking_delta, "content": content_delta, "done": False}

            if finish_reason in ("stop", "tool_calls", "length"):
                yield {
                    "thinking": "",
                    "content": "",
                    "done": True,
                    "tool_calls": accumulated_tool_calls if accumulated_tool_calls else None,
                }
                return

        # 防止没有 finish_reason 时遗漏
        yield {
            "thinking": "",
            "content": "",
            "done": True,
            "tool_calls": accumulated_tool_calls if accumulated_tool_calls else None,
        }


@lru_cache(maxsize=1)
def get_llm() -> LLMClient:
    return LLMClient()