#!/usr/bin/env python3
"""TUI 版入口：组装 core 依赖并启动 Textual 界面。

未来新增 Web / Desktop 版本时，各自新建入口（如 web/main.py），
复用 core 的 load_settings / LLMClient / ToolRegistry / Agent 即可。
"""
from dataclasses import replace
from pathlib import Path

from core.agent import Agent
from core.config import load_settings
from core.llm import LLMClient
from core.skills import SkillManager
from core.tools import (
    ToolRegistry,
    register_cli_tools,
    register_datetime_tools,
    register_file_tools,
    register_fetch_web_tools,
    register_search_tools,
    register_skill_tools,
)
from ui.tui.app import TuiApp


def build(config_path: Path):
    # 工作区 = 启动 aAgent 时的当前目录（项目根），不再依赖 config.ini 的固定路径
    project_root = Path.cwd()
    settings = replace(load_settings(config_path), workspace_root=str(project_root))
    registry = ToolRegistry()

    # Skill 动态加载机制：以 CWD 为项目根目录扫描 .agents/skills/
    skills = SkillManager(project_root)

    register_skill_tools(registry, skills)
    register_cli_tools(registry)
    register_datetime_tools(registry)
    register_file_tools(registry, settings.workspace_root)
    register_fetch_web_tools(registry)
    if settings.search is not None:
        register_search_tools(registry, settings.search.api_key, settings.search.base_url)

    # 将已发现的 Skill 列表注入 System Prompt
    system_prompt = settings.system_prompt
    snippet = skills.prompt_snippet()
    if snippet:
        system_prompt = (
            (system_prompt + "\n\n") if system_prompt else ""
        ) + snippet

    agent = Agent(LLMClient(settings.llm), registry, system_prompt)
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
