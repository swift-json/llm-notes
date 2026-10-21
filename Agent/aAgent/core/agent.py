"""与界面无关的对话编排：消息历史 + 工具调用循环。"""
import json
import time
from typing import Callable, List, Optional

from .llm import LLMClient
from .tools.registry import ToolRegistry

# 工具回调：名称、参数、执行结果、耗时（秒）；供任意界面展示工具调用过程
ToolCallback = Callable[[str, dict, str, float], None]


class Agent:
    def __init__(self, llm: LLMClient, tools: ToolRegistry, system_prompt: str = "") -> None:
        self._llm = llm
        self._tools = tools
        self._system_prompt = system_prompt
        self.messages: List[dict] = []
        self.reset()

    def reset(self) -> None:
        self.messages = []
        if self._system_prompt:
            self.messages.append({"role": "system", "content": self._system_prompt})

    def send(self, text: str, on_tool: Optional[ToolCallback] = None) -> str:
        """发送一条用户消息，自动执行必要的工具调用，返回最终回复。"""
        self.messages.append({"role": "user", "content": text})
        message = self._llm.chat(self.messages, self._tools.schemas())
        while message.tool_calls:
            self.messages.append(message)
            for call in message.tool_calls:
                args = json.loads(call.function.arguments or "{}")
                started = time.perf_counter()
                result = self._tools.execute(call.function.name, args)
                elapsed = time.perf_counter() - started
                if on_tool is not None:
                    on_tool(call.function.name, args, result, elapsed)
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": result,
                })
            message = self._llm.chat(self.messages, self._tools.schemas())
        answer = message.content or ""
        self.messages.append({"role": "assistant", "content": answer})
        return answer
