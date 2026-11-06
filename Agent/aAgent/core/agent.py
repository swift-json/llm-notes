"""与界面无关的对话编排：消息历史 + 工具调用循环 + 上下文压缩。"""
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Union

from .config import DEFAULT_COMPACT_THRESHOLD
from .context_manager import COMPACT_PROMPT, estimate_tokens, save_archive, to_record
from .llm import LLMClient
from .tools.registry import ToolRegistry

# 工具回调：名称、参数、执行结果、耗时（秒）；供任意界面展示工具调用过程
ToolCallback = Callable[[str, dict, str, float], None]
# 流式文本回调：LLM 每输出一段增量文本就会触发；用于打字机效果
StreamCallback = Callable[[str], None]


class Agent:
    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        system_prompt: str = "",
        context_window: int = 128000,
        context_window_is_default: bool = True,
        archive_dir: Union[str, Path] = ".agents/context",
        compact_threshold: float = DEFAULT_COMPACT_THRESHOLD,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._system_prompt = system_prompt
        self._context_window = context_window
        self._context_window_is_default = context_window_is_default
        self._archive_dir = Path(archive_dir)
        self._compact_threshold = compact_threshold
        self._compacting = False  # 压缩进行中：禁止其他工具调用与普通输入
        self._blocked = False     # 已达阈值：暂停接受普通提示词，直到压缩完成
        self._agents_md_loaded = False  # AGENTS.md 是否已注入
        self.messages: List[dict] = []
        self.reset()

    def reset(self) -> None:
        """重置会话：清空消息历史，仅保留 System Prompt 和 AGENTS.md。"""
        self.messages = []
        self._blocked = False
        if self._system_prompt:
            self.messages.append({"role": "system", "content": self._system_prompt})

    @property
    def compacting(self) -> bool:
        return self._compacting

    @property
    def input_blocked(self) -> bool:
        return self._blocked

    @property
    def agents_md_loaded(self) -> bool:
        return self._agents_md_loaded

    def set_agents_md_loaded(self, value: bool) -> None:
        self._agents_md_loaded = value

    def append_message(self, message: dict) -> None:
        """手动追加一条消息（用于恢复会话或注入 AGENTS.md）。"""
        self.messages.append(message)

    def load_messages(self, messages: List[dict], agents_md_loaded: bool = False) -> None:
        """从保存的会话恢复消息历史。"""
        self.messages = list(messages)
        self._agents_md_loaded = agents_md_loaded
        self._blocked = False
        # 恢复时检查是否已被阻止
        used, window, _, _ = self.context_stats()
        if used >= self._compact_threshold * window:
            self._blocked = True

    def context_stats(self) -> tuple:
        """返回 (已用 Token, 上下文窗口, 占用比例, 窗口是否为默认值)。

        优先使用模型 API 返回的 prompt_tokens，否则按字符数估算。
        """
        usage = self._llm.last_usage
        if usage is not None and getattr(usage, "prompt_tokens", None):
            used = usage.prompt_tokens
        else:
            used = estimate_tokens(self.messages)
        return used, self._context_window, used / self._context_window, self._context_window_is_default

    def send(
        self,
        text: str,
        on_tool: Optional[ToolCallback] = None,
        on_stream: Optional[StreamCallback] = None,
    ) -> str:
        """发送一条用户消息，自动执行必要的工具调用，返回最终回复。

        使用流式请求：LLM 每输出一段文本增量就通过 on_stream 回调，供 UI 做打字机效果。
        """
        if self._compacting:
            raise RuntimeError("上下文压缩进行中，请等待压缩完成。")
        if self._blocked:
            raise RuntimeError(
                f"上下文已达 {self._compact_threshold * 100:.0f}% 阈值，请先执行 /compact 压缩上下文。"
            )
        self.messages.append({"role": "user", "content": text})
        message = self._llm.chat_stream(self.messages, self._tools.schemas(), on_stream)
        while message.tool_calls:
            self.messages.append({
                "role": "assistant",
                "content": message.content,
                "tool_calls": message.tool_calls,
            })
            for call in message.tool_calls:
                if isinstance(call, dict):
                    args = json.loads(call["function"]["arguments"] or "{}")
                    name = call["function"]["name"]
                    call_id = call["id"]
                else:
                    args = json.loads(getattr(call.function, "arguments", None) or "{}")
                    name = call.function.name
                    call_id = call.id
                started = time.perf_counter()
                result = self._tools.execute(name, args)
                elapsed = time.perf_counter() - started
                if on_tool is not None:
                    on_tool(name, args, result, elapsed)
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result,
                })
            message = self._llm.chat_stream(self.messages, self._tools.schemas(), on_stream)
        answer = message.content or ""
        self.messages.append({"role": "assistant", "content": answer})
        # 每次响应完成后检查上下文用量，达到阈值则暂停接受新的普通输入
        used, window, _, _ = self.context_stats()
        if used >= self._compact_threshold * window:
            self._blocked = True
        return answer

    def compact(self) -> str:
        """执行上下文压缩：先归档原始上下文，再调用 LLM 生成摘要并替换历史。

        压缩期间不注册任何工具，LLM 只负责生成摘要；保存归档、替换上下文由本方法完成。
        成功返回归档编号；失败时保留原有上下文并抛出异常。
        """
        if self._compacting:
            raise RuntimeError("上下文压缩已在进行中。")
        self._compacting = True
        try:
            # 1. 先完整保存原始上下文，保存成功后才允许继续
            archive_id = save_archive(self._archive_dir, self.messages)
            # 2. 调用 LLM 生成压缩摘要（不带工具，禁止 Function Calling）
            history_text = json.dumps(
                [to_record(m) for m in self.messages], ensure_ascii=False, indent=2
            )
            message = self._llm.chat([
                {"role": "system", "content": COMPACT_PROMPT},
                {"role": "user", "content": "以下是需要压缩的历史消息（JSON 格式）：\n\n" + history_text},
            ])
            summary = (message.content or "").strip()
            if not summary:
                raise RuntimeError("LLM 未返回有效的压缩摘要。")
            # 3. 用摘要替换历史：保留 System Prompt 和 AGENTS.md，追加摘要与归档说明
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            note = (
                f"\n\n> 此前上下文已于 {timestamp} 完成压缩，原始上下文保存在编号为 {archive_id} "
                f"的归档文件中。如需查找历史信息，请使用 recallContext 工具。"
            )
            # 重新构建消息列表：保留初始 system prompt 和 AGENTS.md，丢弃其他
            preserved_messages = []
            if self._system_prompt:
                preserved_messages.append({"role": "system", "content": self._system_prompt})
            # 恢复 AGENTS.md 消息（如果之前注入过）
            if self._agents_md_loaded:
                # 从旧消息中找到 AGENTS.md 消息保留
                for m in self.messages:
                    if m.get("role") == "system" and "AGENTS.md" in (m.get("content") or ""):
                        preserved_messages.append(m)
                        break
            preserved_messages.append({"role": "system", "content": summary + note})
            self.messages = preserved_messages
            self._blocked = False
            return archive_id
        finally:
            self._compacting = False
