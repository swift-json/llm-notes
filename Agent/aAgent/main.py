#!/usr/bin/env python3
"""TUI 版入口：组装 core 依赖并启动 Textual 界面。

未来新增 Web / Desktop 版本时，各自新建入口（如 web/main.py），
复用 core 的 load_settings / LLMClient / ToolRegistry / Agent 即可。
"""
import atexit
import sys
import threading
from dataclasses import replace
from pathlib import Path
from typing import Optional

from core.agent import Agent
from core.config import generate_template, load_settings
from core.llm import LLMClient
from core.session_manager import SessionManager
from core.skills import SkillManager
from core.tools import (
    MCPClientAdapter,
    ToolRegistry,
    register_cli_tools,
    register_context_tools,
    register_datetime_tools,
    register_file_tools,
    register_fetch_web_tools,
    register_mcp_tools,
    register_search_tools,
    register_skill_tools,
)
from ui.tui.app import TuiApp


def ensure_config(config_path: Path) -> bool:
    """确保 config.ini 存在。如果不存在则创建带 mock 信息的模板并返回 False。

    返回值：True 表示配置已就绪，可以继续启动；False 表示刚刚生成了模板，需要用户修改后重启。
    """
    if config_path.exists():
        return True

    # 生成模板
    print(f"[aAgent] 未找到 config.ini，正在创建模板: {config_path}", file=sys.stderr)
    generate_template(config_path)
    print(
        "[aAgent] 已创建 config.ini 模板，请修改 api_key 等配置后重新启动 aAgent。",
        file=sys.stderr,
    )
    print(f"[aAgent] 模板文件路径: {config_path}", file=sys.stderr)
    return False


def build(config_path: Path, on_mcp_loaded: Optional[callable] = None):
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
    # 历史上下文归档目录：<项目根>/.agents/context/
    archive_dir = project_root / ".agents" / "context"
    register_context_tools(registry, archive_dir)
    if settings.search is not None:
        register_search_tools(registry, settings.search.api_key, settings.search.base_url)

    # MCP Client：支持异步加载
    mcp_adapter: Optional[MCPClientAdapter] = register_mcp_tools(
        registry,
        project_root / ".mcp.json",
        connect_timeout=settings.mcp.connect_timeout,
        call_timeout=settings.mcp.call_timeout,
        disconnect_timeout=settings.mcp.disconnect_timeout,
        async_load=settings.mcp.async_load,
        on_loaded=on_mcp_loaded,
    )

    # 将已发现的 Skill 列表注入 System Prompt
    system_prompt = settings.system_prompt
    snippet = skills.prompt_snippet()
    if snippet:
        system_prompt = (
            (system_prompt + "\n\n") if system_prompt else ""
        ) + snippet

    agent = Agent(
        LLMClient(settings.llm),
        registry,
        system_prompt,
        context_window=settings.llm.context_window,
        context_window_is_default=settings.llm.context_window_is_default,
        archive_dir=archive_dir,
        compact_threshold=settings.agent.compact_threshold,
    )
    schema = [
        {"name": item["function"]["name"], "description": item["function"]["description"]}
        for item in registry.schemas()
    ]

    # SessionManager
    session_dir = project_root / settings.session.session_dir
    session_mgr = SessionManager(session_dir, settings.workspace_root)

    # 加载 AGENTS.md（一次注入，全程复用）
    agents_md_content = session_mgr.load_agents_md(project_root)
    if agents_md_content:
        agent.append_message(SessionManager.make_agents_md_message(agents_md_content))
        agent.set_agents_md_loaded(True)
        print(f"[aAgent] 已加载 AGENTS.md 注入到会话上下文", file=sys.stderr)

    return agent, settings, schema, mcp_adapter, session_mgr, project_root


def main() -> None:
    config_path = Path(__file__).with_name("config.ini")

    # 检查并自动生成 config.ini
    if not ensure_config(config_path):
        sys.exit(1)

    # 先构建，但把 MCP 加载回调传给 TuiApp，让它在界面中动态刷新
    # TuiApp 内部会在 on_mount 后通过 on_mcp_loaded 回调刷新边栏
    app_holder = {"app": None}  # 用于闭包中引用 TuiApp 实例

    def on_mcp_loaded():
        """MCP 异步加载完成后回调 TuiApp 刷新界面。"""
        app = app_holder.get("app")
        if app is not None:
            try:
                app.refresh_after_mcp_load()
            except Exception as exc:
                print(f"[MCP] 刷新 TUI 失败: {exc}", file=sys.stderr)

    agent, settings, tools, mcp_adapter, session_mgr, project_root = build(config_path, on_mcp_loaded)

    # 注册退出清理：断开所有 MCP Server 连接
    if mcp_adapter:
        atexit.register(mcp_adapter.disconnect_all)

    app = TuiApp(
        agent,
        model=settings.llm.model,
        base_url=settings.llm.base_url,
        workspace=settings.workspace_root,
        tools=tools,
        mcp_adapter=mcp_adapter,
        session_mgr=session_mgr,
        settings=settings,
        project_root=project_root,
    )
    app_holder["app"] = app
    app.run()


if __name__ == "__main__":
    main()
