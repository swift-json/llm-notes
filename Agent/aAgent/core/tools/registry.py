"""工具抽象与注册表：统一工具定义、Schema 生成和调用分发。"""
from dataclasses import dataclass, field
from typing import Callable, Dict, List


@dataclass
class Tool:
    name: str
    description: str
    handler: Callable[[dict], str]
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def add(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def schemas(self) -> List[dict]:
        return [tool.schema() for tool in self._tools.values()]

    def execute(self, name: str, args: dict) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"未知工具: {name}"
        try:
            return tool.handler(args)
        except PermissionError as exc:
            return str(exc)
        except FileNotFoundError as exc:
            return f"文件/目录不存在: {exc}"
        except Exception as exc:
            return f"执行错误: {type(exc).__name__}: {exc}"
