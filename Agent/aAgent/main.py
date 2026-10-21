#!/usr/bin/env python3
"""TUI 版入口：组装 core 依赖并启动 Textual 界面。

未来新增 Web / Desktop 版本时，各自新建入口（如 web/main.py），
复用 core 的 load_settings / LLMClient / ToolRegistry / Agent 即可。
"""
from pathlib import Path

from core.agent import Agent
from core.config import load_settings
from core.llm import LLMClient
from core.tools import ToolRegistry, register_datetime_tools, register_file_tools
from ui.tui.app import TuiApp


def build(config_path: Path):
    settings = load_settings(config_path)
    registry = ToolRegistry()
    register_datetime_tools(registry)
    register_file_tools(registry, settings.workspace_root)
    agent = Agent(LLMClient(settings.llm), registry, settings.system_prompt)
    schema = [
        {"name": item["function"]["name"], "description": item["function"]["description"]}
        for item in registry.schemas()
    ]
    return agent, settings, schema


def main() -> None:
    agent, settings, tools = build(Path(__file__).with_name("config.ini"))
    TuiApp(
        agent,
        model=settings.llm.model,
        base_url=settings.llm.base_url,
        workspace=settings.workspace_root,
        tools=tools,
    ).run()


if __name__ == "__main__":
    main()
