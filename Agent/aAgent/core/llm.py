"""LLM 提供商封装：界面层不直接依赖任何 SDK 细节。"""
from typing import Callable, List, Optional

from openai import OpenAI

from .config import LLMConfig


class LLMClient:
    def __init__(self, config: LLMConfig) -> None:
        self._client = OpenAI(base_url=config.base_url, api_key=config.api_key)
        self._model = config.model
        # 最近一次响应的 usage（含 prompt_tokens），用于上下文长度监控
        self.last_usage = None

    def chat(self, messages: List[dict], tools: Optional[List[dict]] = None):
        """非流式请求，返回完整 assistant message。用于 /compact 等不需要打字机效果的场景。"""
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools or None,
        )
        self.last_usage = getattr(response, "usage", None)
        return response.choices[0].message

    def chat_stream(
        self,
        messages: List[dict],
        tools: Optional[List[dict]] = None,
        on_delta: Optional[Callable[[str], None]] = None,
    ):
        """流式请求，边收 token 边通过 on_delta 回调增量内容。

        返回完整的 assistant message（content + tool_calls），供上层继续工具循环。
        """
        stream = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools or None,
            stream=True,
        )
        full_content = ""
        tool_calls: list = []  # 流式工具调用的累积容器（需按 index 合并）
        finish_reason = None

        for chunk in stream:
            if chunk.usage is not None:
                self.last_usage = chunk.usage
            delta = chunk.choices[0].delta
            if chunk.choices[0].finish_reason is not None:
                finish_reason = chunk.choices[0].finish_reason

            # 文本增量 → 只有"最终回复阶段"才触发打字机（不含 tool_calls 循环中模型的中间输出）
            if delta.content and not delta.tool_calls:
                full_content += delta.content
                if on_delta is not None:
                    on_delta(delta.content)

            # 工具调用增量（流式模式下 chunk 返回 tool_calls 增量）
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index if tc_delta.index is not None else 0
                    while len(tool_calls) <= idx:
                        tool_calls.append({"id": None, "type": "function", "function": {"name": None, "arguments": ""}})
                    slot = tool_calls[idx]
                    if tc_delta.id:
                        slot["id"] = tc_delta.id
                    if tc_delta.function.name:
                        slot["function"]["name"] = tc_delta.function.name
                    if tc_delta.function.arguments:
                        slot["function"]["arguments"] += tc_delta.function.arguments

        # 组装完整的 assistant message（保持与非流式 chat 返回值同一结构）
        class _Msg:
            pass
        msg = _Msg()
        msg.content = full_content or None
        msg.tool_calls = None
        if any(tc["id"] and tc["function"]["name"] for tc in tool_calls):
            msg.tool_calls = tool_calls
        msg.finish_reason = finish_reason
        return msg
