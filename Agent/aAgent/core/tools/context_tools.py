"""历史上下文检索工具：在 .agents/context/ 归档中做本地关键词全文检索。"""
from pathlib import Path
from typing import Union

from ..context_manager import search_archives
from .registry import Tool, ToolRegistry


def register_context_tools(registry: ToolRegistry, archive_dir: Union[str, Path]) -> None:
    archive_dir = str(archive_dir)
    registry.add(Tool(
        "recallContext",
        "检索已归档的历史上下文（/compact 压缩前保存的原始记录）。"
        "当压缩摘要缺少某些历史细节时调用，返回相关片段、归档编号和所在行号。",
        lambda args: search_archives(archive_dir, args["text"], args.get("id") or None),
        {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "可选，归档编号（如 20261022-153000）。提供时只检索该归档，省略时检索全部归档。",
                },
                "text": {
                    "type": "string",
                    "description": "需要查找的关键词或文本内容",
                },
            },
            "required": ["text"],
        },
    ))
