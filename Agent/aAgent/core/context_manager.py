"""上下文管理：Token 估算、原始上下文归档（jsonl）、归档关键词检索。

仅使用本地文件与关键词匹配，不依赖向量数据库或 Embedding 框架。
"""
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union

# 上下文压缩专用 Prompt：指导 LLM 把历史对话整理为可接力的工作摘要
COMPACT_PROMPT = """你是一名 AI Agent 的上下文管理助手。当前会话即将达到上下文窗口限制，需要将历史对话压缩为一份高质量的工作摘要，以便 Agent 在新的上下文中继续执行任务。

请认真阅读提供的历史上下文，提取对后续工作仍然有价值的信息，并生成一份约 5,000 Tokens 的 Markdown 摘要。

摘要应重点保留以下内容：

1. **用户目标与要求**：用户希望完成什么任务？有哪些必须遵守的约束、偏好和验收条件？
2. **已经完成的工作**：哪些任务已经完成？实现了哪些功能？获得了哪些已经验证的结果？
3. **当前工作状态**：Agent 正在处理什么任务？当前进展到哪一步？是否存在尚未解决的问题？
4. **关键技术信息**：保留重要的文件路径、函数名称、接口定义、配置项、执行命令、错误信息和必要的代码片段。
5. **关键决策与原因**：记录用户和 Agent 已经确定的技术方案，以及重要的设计取舍。
6. **下一步任务**：明确接下来应该执行的操作，以及需要继续验证的事项。

请遵守以下要求：

- 优先保留对后续任务有直接影响的信息，删除寒暄、重复讨论、过时的尝试和无关内容。
- 对已经验证的事实与尚未验证的推测作出明确区分。
- 不要将计划完成的任务描述为已经完成。
- 重要的文件路径、函数名称、配置名称和命令应保留准确原文。
- 对失败的尝试，只保留有助于避免重复错误的信息。
- 如果信息存在冲突，应优先保留用户最新确认的要求，并简要说明仍然存在的冲突。
- 如果某些历史细节无法在摘要中完整保留，可简要说明它们已保存到原始上下文归档中，后续可以通过 `recallContext` 工具重新检索。
- 使用清晰的 Markdown 结构输出摘要，不要附加解释或无关内容。

**最终目标：使一个从未阅读过原始对话的 Agent，仅凭这份摘要，就能够理解当前任务、继承关键决策，并继续开展工作。**"""


def _text_tokens(text: str) -> int:
    """粗略估算文本 Token 数：中文字符按 1 计，其余按 4 字符 ≈ 1 Token。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk + (len(text) - cjk) // 4


def to_record(message: Union[dict, object]) -> dict:
    """把 dict 消息或 openai SDK 的 ChatCompletionMessage 对象统一转为可序列化的 dict。"""
    if isinstance(message, dict):
        record = {}
        for key in ("role", "content", "tool_call_id", "name"):
            if key in message:
                record[key] = message[key]
        if message.get("tool_calls"):
            record["tool_calls"] = message["tool_calls"]
        return record
    record = {"role": getattr(message, "role", "assistant"), "content": getattr(message, "content", None)}
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        record["tool_calls"] = [tc.model_dump() for tc in tool_calls]
    return record


def estimate_tokens(messages: List[Union[dict, object]]) -> int:
    """估算整段消息历史的 Token 数（无法从 API 获取 usage 时的兜底方案）。"""
    total = 0
    for message in messages:
        record = to_record(message)
        total += 4  # 每条消息的固定开销
        for key in ("role", "content", "name"):
            value = record.get(key)
            if value:
                total += _text_tokens(str(value))
        if record.get("tool_calls"):
            total += _text_tokens(json.dumps(record["tool_calls"], ensure_ascii=False))
    return total


def save_archive(archive_dir: Union[str, Path], messages: List[Union[dict, object]]) -> str:
    """把原始上下文完整保存为 jsonl 归档，返回归档编号（如 20261022-153000）。

    归档保留消息的角色、内容、工具调用参数、工具返回结果与顺序。
    """
    archive_dir = Path(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = archive_dir / f"{archive_id}.jsonl"
    suffix = 2
    while path.exists():  # 同一秒内多次压缩时避免覆盖
        archive_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{suffix}"
        path = archive_dir / f"{archive_id}.jsonl"
        suffix += 1
    with path.open("w", encoding="utf-8") as f:
        for message in messages:
            f.write(json.dumps(to_record(message), ensure_ascii=False) + "\n")
    return archive_id


def search_archives(
    archive_dir: Union[str, Path],
    text: str,
    archive_id: Optional[str] = None,
    max_results: int = 10,
    snippet_radius: int = 250,
    max_chars: int = 4000,
) -> str:
    """在归档文件中做关键词全文检索，返回相关片段（含归档编号与行号）。"""
    archive_dir = Path(archive_dir)
    keywords = [k.lower() for k in text.split() if k.strip()]
    if not keywords:
        return "请提供要检索的关键词（text 参数）。"
    if archive_id:
        files = [archive_dir / f"{archive_id}.jsonl"]
        if not files[0].exists():
            return f"未找到归档文件: {archive_id}"
    else:
        files = sorted(archive_dir.glob("*.jsonl"))
        if not files:
            return "暂无历史上下文归档。"

    results: List[str] = []
    total = 0
    truncated = False
    for path in files:
        for lineno, line in enumerate(path.open(encoding="utf-8"), 1):
            if len(results) >= max_results or total >= max_chars:
                truncated = True
                break
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = record.get("content") or ""
            if record.get("tool_calls"):  # 工具调用参数也纳入检索范围
                content += "\n" + json.dumps(record["tool_calls"], ensure_ascii=False)
            lowered = content.lower()
            hit = next((k for k in keywords if k in lowered), None)
            if hit is None:
                continue
            pos = lowered.index(hit)
            start = max(0, pos - snippet_radius)
            end = min(len(content), pos + snippet_radius)
            snippet = ("…" if start > 0 else "") + content[start:end] + ("…" if end < len(content) else "")
            block = f"归档 {path.stem} · 第 {lineno} 行 · role={record.get('role', '?')}\n{snippet}"
            results.append(block)
            total += len(block)
        if truncated:
            break

    if not results:
        where = f"归档 {archive_id}" if archive_id else "任何归档"
        return f"未在{where}中找到与「{text}」相关的内容。"
    if truncated:
        results.append("…（匹配较多，结果已截断；可换用更精确的关键词或指定 id 检索）")
    return "\n\n".join(results)
