import logging
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI

from app.shared.errors import LLMServiceError

os.environ["NO_PROXY"] = "aliyuncs.com,dashscope.aliyuncs.com"
load_dotenv()
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
        system: Optional[str] = None,
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
            # logger.info("模型响应: %s", resp.model_dump())
        except Exception as e:
            raise LLMServiceError(f"模型请求失败: {e}") from e

        logger.debug("模型响应: %s", getattr(resp, "id", ""))
        return resp.model_dump()


@lru_cache(maxsize=1)
def get_llm() -> LLMClient:
    return LLMClient()