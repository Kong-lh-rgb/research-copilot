import logging
import os
from functools import lru_cache
from typing import Any, AsyncGenerator, Dict, List, Optional
from dotenv import load_dotenv
from openai import AsyncOpenAI
import httpx
from app.core.exceptions import LLMServiceError

load_dotenv()

os.environ.setdefault("NO_PROXY", "aliyuncs.com,dashscope.aliyuncs.com")

logger = logging.getLogger(__name__)

# 节点角色 → 模型 env 变量的映射
# 每个角色可在 .env 中单独指定模型，留空则回退到 OPENAI_MODEL
_ROLE_MODEL_ENV: Dict[str, str] = {
    "controller":  "MODEL_CONTROLLER",
    "planner":     "MODEL_PLANNER",
    "worker":      "MODEL_WORKER",
    "reviewer":    "MODEL_REVIEWER",
    "simple_chat": "MODEL_SIMPLE_CHAT",
}


class LLMConfigError(RuntimeError):
    pass


def _sanitize_thinking_content(thinking: str) -> str:
    """对思考过程进行脱敏，隐藏工具调用细节和敏感信息"""
    import re
    if not thinking:
        return thinking
    
    # 隐藏工具调用的细节（例如：function_call: {name: "xxx", arguments: {...}}）
    thinking = re.sub(
        r'"?function_call"?\s*:\s*\{[^}]*\}',
        '[工具调用]',
        thinking,
        flags=re.IGNORECASE
    )
    
    # 隐藏 tool_calls 中的工具名和参数
    thinking = re.sub(
        r'"?name"?\s*:\s*"[^"]*"',
        '"name": "[已隐藏]"',
        thinking,
        flags=re.IGNORECASE
    )
    thinking = re.sub(
        r'"?arguments"?\s*:\s*\{[^}]*\}',
        '"arguments": "[已隐藏]"',
        thinking,
        flags=re.IGNORECASE
    )
    
    # 隐藏具体的工具名（例如 tavily_search, get_stock_history 等）
    thinking = re.sub(
        r'\b(tavily_search|get_stock_history|get_financial_\w+|send_email|send_wechat|maps_\w+|screen_stocks)\b',
        '[工具]',
        thinking,
        flags=re.IGNORECASE
    )
    
    return thinking


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

        # 设置超时：连接10秒，读取120秒，写入10秒
        self._client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url or None,
            timeout=httpx.Timeout(120.0, connect=10.0, write=10.0),
            max_retries=3,  # 最多重试3次
        )

        logging.getLogger("openai").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)

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

    # ------------------------------------------------------------------ #
    #  私有工具方法                                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _merge_tc_chunk(
        accumulated: List[Dict[str, Any]],
        tc_chunk: Any,
    ) -> None:
        """将单个 tool_call 流式分片合并到 accumulated 列表中。"""
        idx = tc_chunk.index
        # 按需扩展列表，保证 idx 位置存在
        while len(accumulated) <= idx:
            accumulated.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})

        slot = accumulated[idx]
        if tc_chunk.id:
            slot["id"] = tc_chunk.id
        if tc_chunk.function:
            slot["function"]["name"]      += tc_chunk.function.name      or ""
            slot["function"]["arguments"] += tc_chunk.function.arguments or ""

    def _make_done_chunk(self, tool_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
        """构造流结束标记 chunk。"""
        return {
            "thinking":   "",
            "content":    "",
            "done":       True,
            "tool_calls": tool_calls or None,
        }

    # ------------------------------------------------------------------ #
    #  公开接口                                                            #
    # ------------------------------------------------------------------ #

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, str], None]:
        """流式调用 LLM，逐 token yield {"thinking": str, "content": str, "done": bool}。

        流结束时额外 yield 一个 done=True 的 chunk，其中包含完整的 tool_calls 列表。
        """
        # --- 构造请求 ---
        request_payload: Dict[str, Any] = {
            "model":    model or self._model,
            "messages": messages,
            "stream":   True,
        }
        if tools:
            request_payload["tools"]       = tools
            request_payload["tool_choice"] = tool_choice or "auto"
        if temperature is not None:
            request_payload["temperature"] = temperature

        try:
            stream = await self._client.chat.completions.create(**request_payload)
        except Exception as e:
            raise LLMServiceError(f"模型流式请求失败: {e}") from e

        # --- 处理流 ---
        accumulated_tool_calls: List[Dict[str, Any]] = []

        async for chunk in stream:
            if not chunk.choices:
                continue

            delta         = chunk.choices[0].delta
            finish_reason = chunk.choices[0].finish_reason

            # 1. 合并 tool_call 分片
            for tc_chunk in (delta.tool_calls or []):
                self._merge_tc_chunk(accumulated_tool_calls, tc_chunk)

            # 2. yield 文本 / 思考内容
            thinking_delta = getattr(delta, "reasoning_content", None) or ""
            thinking_delta = _sanitize_thinking_content(thinking_delta)  # 脱敏工具调用细节
            content_delta  = delta.content or ""
            if thinking_delta or content_delta:
                yield {"thinking": thinking_delta, "content": content_delta, "done": False}

            # 3. 流结束
            if finish_reason in ("stop", "tool_calls", "length"):
                yield self._make_done_chunk(accumulated_tool_calls)
                return

        # 兜底：未收到 finish_reason（网络截断等异常情况）
        yield self._make_done_chunk(accumulated_tool_calls)


@lru_cache(maxsize=1)
def get_llm() -> "LLMClient":
    """返回使用默认 OPENAI_MODEL 的共享实例（向后兼容）。"""
    return LLMClient()


@lru_cache(maxsize=8)
def get_llm_for_role(role: str) -> "LLMClient":
    """根据节点角色返回对应的 LLMClient 实例（带缓存）。 """
    env_key = _ROLE_MODEL_ENV.get(role, "")
    model = (os.getenv(env_key, "").strip() if env_key else "") or os.getenv("OPENAI_MODEL", "").strip() or None
    logger.debug("[LLMClient] role=%s → model=%s", role, model)
    return LLMClient(model=model)