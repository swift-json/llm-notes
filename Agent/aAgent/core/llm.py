"""LLM 提供商封装：界面层不直接依赖任何 SDK 细节。"""
from typing import List, Optional

from openai import OpenAI

from .config import LLMConfig


class LLMClient:
    def __init__(self, config: LLMConfig) -> None:
        self._client = OpenAI(base_url=config.base_url, api_key=config.api_key)
        self._model = config.model

    def chat(self, messages: List[dict], tools: Optional[List[dict]] = None):
        """发起一次对话请求，返回 assistant message。"""
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools or None,
        )
        return response.choices[0].message
