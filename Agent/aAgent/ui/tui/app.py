"""终端界面（Textual）：只负责输入、展示与线程调度，业务逻辑全部来自 core。"""
import json
import re
import sys
import uuid
from typing import Any, Dict, List, Literal, Optional

from rich.console import Group
from rich.json import JSON
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Key
from textual.message import Message
from textual.widgets import Button, Footer, Header, RichLog, Static, TextArea

from core.agent import Agent
from core.config import Settings
from core.session_manager import SessionManager
from core.tools.mcp_client import MCPClientAdapter

USER_COLOR = "#58a6ff"
AI_COLOR = "#1f6feb"
TOOL_COLOR = "#3fb950"
MUTED = "#8b949e"
MCP_COLOR = "#bc8cff"

# Spinner frames
_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _clean_latex(text: str) -> str:
    text = re.sub(r"\$\$(.+?)\$\$", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"(?<!\$)\$([^$\n]+?)\$(?!\$)", r"\1", text)
    return text


# ============== 斜杠命令定义 ==============

SLASH_COMMANDS: Dict[str, Dict] = {
    "/new": {
        "desc": "新建会话，自动保存当前会话历史",
        "handler": "cmd_new_session",
    },
    "/resume": {
        "desc": "恢复历史会话（弹出选择面板）",
        "handler": "cmd_resume_session",
    },
    "/save": {
        "desc": "保存当前会话到文件",
        "handler": "cmd_save_session",
    },
    "/quit": {
        "desc": "退出 aAgent（自动保存）",
        "handler": "cmd_quit",
    },
    "/help": {
        "desc": "显示所有斜杠命令帮助",
        "handler": "cmd_help",
    },
    "/compact": {
        "desc": "压缩上下文（归档 + LLM 摘要）",
        "handler": "cmd_compact",
    },
    "/clear": {
        "desc": "清除当前屏幕显示的消息",
        "handler": "cmd_clear",
    },
    "/tools": {
        "desc": "列出所有可用工具（本地 + MCP）",
        "handler": "cmd_tools",
    },
    "/status": {
        "desc": "显示当前会话状态和上下文用量",
        "handler": "cmd_status",
    },
}


def _common_prefix(items: List[str]) -> str:
    """返回一组字符串的最长公共前缀（区分大小写）。"""
    if not items:
        return ""
    prefix = items[0]
    for item in items[1:]:
        while not item.startswith(prefix):
            prefix = prefix[:-1]
            if not prefix:
                return ""
    return prefix


# ============== 斜杠/会话面板（主 App 内嵌 widget） ==============

# ============== 输入框 ==============

class PromptArea(TextArea):
    """多行输入框：Enter 发送，Ctrl+J 换行，Tab 补全斜杠命令。"""

    class SubmitRequested(Message):
        def __init__(self, text: str, control: "PromptArea") -> None:
            super().__init__()
            self.text = text
            self._control = control

        @property
        def control(self) -> "PromptArea":
            return self._control

    class ComplementRequested(Message):
        """请求补全当前斜杠命令。"""

    async def _on_key(self, event: Key) -> None:
        key = event.key
        if key == "enter" or (key.endswith("+enter") and not key.startswith("shift+")):
            event.prevent_default()
            event.stop()
            self.post_message(self.SubmitRequested(self.text, self))
            return
        if key == "ctrl+j" or key == "shift+enter":
            event.prevent_default()
            event.stop()
            start, end = self.selection
            self._replace_via_keyboard("\n", start, end)
            return
        # Tab：斜杠补全面板打开时用于补全（否则保留 TextArea 默认缩进行为）
        if key == "tab" and getattr(self.app, "slash_panel_open", False):
            event.prevent_default()
            event.stop()
            self.post_message(self.ComplementRequested())
            return
        await super()._on_key(event)


# ============== 主界面 ==============

class TuiApp(App):
    CSS = """
    Screen { background: #0d1117; color: #c9d1d9; }
    Header { background: #161b22; color: #c9d1d9; }
    Footer { background: #161b22; color: #8b949e; }
    #body { height: 1fr; }
    #main { width: 1fr; }
    #info {
        height: auto; margin: 0 1; padding: 0 1;
        background: #161b22; border: round #30363d; color: #c9d1d9;
    }
    #log { margin: 0 1; background: #0d1117; border: none; }
    #sidebar {
        width: 48; background: #11161d; border-left: solid #30363d; padding: 0 1;
    }
    #session-info { height: auto; padding: 0 0 1 0; }
    #local-tools { height: auto; padding: 0 0 1 0; }
    #mcp-section { height: auto; padding: 0 0 1 0; }
    #status { height: 1; background: #161b22; color: #8b949e; padding: 0 1; }
    #prompt-wrap { height: auto; margin: 0 1 1 1; }
    #spinner {
        height: 6; width: 3; content-align: center middle;
        color: #f0883e; background: #0d1117;
    }
    #prompt-box {
        width: 1fr; height: 6;
        border: round #4a9eff; background: #0d1117;
    }
    #prompt-box:focus-within { border: round #58a6ff; }
    #prompt { height: 1fr; border: none; background: #0d1117; }
    #prompt:focus { border: none; }
    #btn-row { height: 1; }
    #btn-spacer { width: 1fr; }
    #send-btn {
        width: 3; min-width: 3; height: 1;
        border: none; background: #4a9eff; color: #ffffff;
        text-style: bold;
    }
    #send-btn:hover { background: #58a6ff; }
    #send-btn:focus { background: #58a6ff; }
    /* ---- 斜杠/会话面板（内嵌 widget） ---- */
    #slash-panel {
        height: 12; margin: 0 1;
        background: #0d1117; border: round #30363d;
        display: none;
    }
    #slash-panel.open { display: block; }
    #sp-header {
        height: 1; padding: 0 1;
        background: #161b22; border-bottom: solid #30363d;
    }
    #sp-title { color: #58a6ff; }
    #sp-filter { color: #8b949e; }
    #sp-count { color: #484f58; }
    #sp-list { padding: 0; height: 8; overflow-y: scroll; }
    #sp-footer {
        height: 1; padding: 0 1;
        background: #0d1117; border-top: solid #21262d;
    }
    #sp-hint { color: #484f58; text-style: italic; }
    #session-panel {
        height: 18; margin: 0 1;
        background: #0d1117; border: round #30363d;
        display: none;
    }
    #session-panel.open { display: block; }
    #ss-header {
        height: 1; padding: 0 1;
        background: #161b22; border-bottom: solid #30363d;
    }
    #ss-title { color: #3fb950; }
    #ss-count { color: #484f58; }
    #ss-list { padding: 0; height: 14; overflow-y: scroll; }
    #ss-footer {
        height: 1; padding: 0 1;
        background: #0d1117; border-top: solid #21262d;
    }
    #ss-hint { color: #484f58; text-style: italic; }
    """

    BINDINGS = [
        ("ctrl+q", "quit", "退出"),
        ("ctrl+n", "new_session", "新会话"),
        ("ctrl+l", "clear_log", "清屏"),
        ("ctrl+b", "toggle_sidebar", "侧栏"),
        ("ctrl+s", "save_session", "保存会话"),
        ("ctrl+r", "resume_session", "恢复会话"),
    ]

    def __init__(
        self,
        agent: Agent,
        model: str = "",
        base_url: str = "",
        workspace: str = "",
        tools: Optional[List[dict]] = None,
        mcp_adapter: Optional[MCPClientAdapter] = None,
        session_mgr: Optional[SessionManager] = None,
        settings: Optional[Settings] = None,
        project_root: Optional[object] = None,
    ) -> None:
        super().__init__()
        self._agent = agent
        self._model = model
        self._base_url = base_url
        self._workspace = workspace
        self._local_tools = tools or []
        self._mcp_adapter = mcp_adapter
        self._session_mgr = session_mgr
        self._settings = settings
        self._project_root = project_root

        # 当前工具列表（本地 + MCP 动态追加）
        self._all_tools = list(self._local_tools)
        self._mcp_loading = bool(mcp_adapter and settings and settings.mcp.async_load)

        self._session_id = uuid.uuid4().hex[:8]
        self._turns = 0
        self._busy = False
        self._spin_idx = 0
        self.title = "aAgent"
        self.sub_title = model

        # Panel 状态（内嵌 widget，display 切换）
        self._panel_open: Literal["slash", "session", None] = None
        self._slash_filter = ""        # 斜杠命令过滤字符串（不含前导 /）
        self._slash_selected = 0       # 选中索引
        self._slash_filter_input = ""  # 原始输入（可能包含 /）
        self._session_selected = 0
        self._session_list: List[dict] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="main"):
                yield Static(self._banner_markup(), id="info")
                yield RichLog(id="log", markup=False, wrap=True)
            with VerticalScroll(id="sidebar"):
                yield Static(self._session_markup(), id="session-info")
                yield Static(self._local_tools_markup(), id="local-tools")
                yield Static(self._mcp_markup(), id="mcp-section")
        yield Static(self._status_markup(), id="status")
        # ---- 斜杠命令补全面板（输入 / 时弹出，显示在输入框正上方） ----
        with Vertical(id="slash-panel"):
            with Horizontal(id="sp-header"):
                yield Static("", id="sp-title")
                yield Static("", id="sp-filter")
                yield Static("", id="sp-count")
            yield Static("", id="sp-list")
            with Horizontal(id="sp-footer"):
                yield Static("", id="sp-hint")
        # ---- 会话恢复面板 ----
        with Vertical(id="session-panel"):
            with Horizontal(id="ss-header"):
                yield Static("", id="ss-title")
                yield Static("", id="ss-count")
            yield Static("", id="ss-list")
            with Horizontal(id="ss-footer"):
                yield Static("", id="ss-hint")
        with Horizontal(id="prompt-wrap"):
            yield Static("", id="spinner")
            with Vertical(id="prompt-box"):
                yield PromptArea(
                    placeholder="输入问题，Enter 发送，Ctrl+J 换行…  输入 / 查看命令",
                    id="prompt",
                    language=None,
                )
                with Horizontal(id="btn-row"):
                    yield Static("", id="btn-spacer")
                    yield Button("↑", id="send-btn")
        yield Footer()

    def on_mount(self) -> None:
        self._set_busy(False)
        self._welcome()
        spinner_interval = self._settings.ui.spinner_interval if self._settings else 0.12
        self.set_interval(spinner_interval, self._tick_spinner)
        pa = self.query_one("#prompt", TextArea)
        pa.show_cursor = False
        sys.stdout.write("\x1b[5 q")
        sys.stdout.flush()

    def on_unmount(self) -> None:
        sys.stdout.write("\x1b[2 q")
        sys.stdout.flush()
        self._auto_save()

    def refresh_after_mcp_load(self) -> None:
        self._mcp_loading = False
        self._refresh_all_tools_from_registry()
        self.call_from_thread(self._refresh_sidebar)

    def _refresh_all_tools_from_registry(self) -> None:
        registry = self._agent._tools
        self._all_tools = [
            {"name": item["function"]["name"], "description": item["function"]["description"]}
            for item in registry.schemas()
        ]
        self._local_tools = [t for t in self._all_tools if not t["name"].startswith("mcp_")]

    # ---------- Spinner ----------

    def _tick_spinner(self) -> None:
        if not self._busy:
            return
        self._spin_idx = (self._spin_idx + 1) % len(_SPINNER_FRAMES)
        self.query_one("#spinner", Static).update(_SPINNER_FRAMES[self._spin_idx])

    # ---------- 边栏刷新 ----------

    def _refresh_sidebar(self) -> None:
        self.query_one("#session-info", Static).update(self._session_markup())
        self.query_one("#local-tools", Static).update(self._local_tools_markup())
        self.query_one("#mcp-section", Static).update(self._mcp_markup())
        self.query_one("#info", Static).update(self._banner_markup())
        self.query_one("#status", Static).update(self._status_markup())

    # ---------- 布局文本 ----------

    def _banner_markup(self) -> str:
        return (
            f"[b {USER_COLOR}]aAgent[/]  [dim]·[/]  "
            f"[b {TOOL_COLOR}]{len(self._all_tools)}[/] 个工具  "
            f"[b {MCP_COLOR}]·[/]  "
            f"[b {MCP_COLOR}]{self._mcp_tool_count()}[/] MCP  "
            f"[dim]·[/]  {escape(self._model)}\n"
            f"[{MUTED}]工作区[/]  {escape(self._workspace)}\n"
            f"[{MUTED}]上下文[/]  {self._context_usage_markup()}\n"
            f"[{MUTED}]Enter 发送   Ctrl+J 换行   /help 命令帮助   Ctrl+N 新会话   Ctrl+L 清屏   Ctrl+R 恢复   Ctrl+Q 退出[/]"
        )

    def _mcp_tool_count(self) -> int:
        if self._mcp_adapter:
            return sum(len(v) for v in self._mcp_adapter._server_tools.values())
        return 0

    def _context_usage_markup(self) -> str:
        used, window, ratio, is_default = self._agent.context_stats()
        color = "#f85149" if ratio >= 0.8 else ("#d29922" if ratio >= 0.6 else TOOL_COLOR)
        default_note = f" [{MUTED}]（默认）[/]" if is_default else ""
        return f"[{color}]{used / 1000:.1f}k / {window / 1000:.0f}k（{ratio * 100:.1f}%）[/]{default_note}"

    def _session_markup(self) -> str:
        state = f"[yellow]思考中[/]" if self._busy else f"[{TOOL_COLOR}]就绪[/]"
        agents_note = f"  [dim]· AGENTS.md[/]" if self._agent.agents_md_loaded else ""
        return (
            f"[b]会话[/]{agents_note}\n"
            f"[{MUTED}]模型[/]    {escape(self._model)}\n"
            f"[{MUTED}]接口[/]    {escape(self._base_url)}\n"
            f"[{MUTED}]工作区[/]  {escape(self._workspace)}\n"
            f"[{MUTED}]会话ID[/]  {self._session_id}\n"
            f"[{MUTED}]轮次[/]    {self._turns}\n"
            f"[{MUTED}]消息[/]    {len(self._agent.messages)}\n"
            f"[{MUTED}]状态[/]    {state}"
        )

    def _local_tools_markup(self) -> str:
        lines = [f"[b]本地工具 · {len(self._local_tools)}[/]"]
        for tool in self._local_tools:
            lines.append(f"[b {TOOL_COLOR}]• {escape(tool['name'])}[/]")
            lines.append(f"[{MUTED}]{escape(tool['description'])}[/]")
        return "\n".join(lines)

    def _mcp_markup(self) -> str:
        if self._mcp_loading:
            return f"[b]MCP 服务器[/]\n[yellow]◐ 加载中…[/]"
        if not self._mcp_adapter or not self._mcp_adapter._connections:
            return f"[b]MCP 服务器[/]\n[dim]未配置或未连接[/]"
        lines = [f"[b]MCP 服务器 · {len(self._mcp_adapter._connections)}[/]"]
        for server_name, tool_names in self._mcp_adapter._server_tools.items():
            conn = self._mcp_adapter._connections.get(server_name)
            status = "✓" if (conn and conn.connected) else "✗"
            status_color = TOOL_COLOR if status == "✓" else "#f85149"
            lines.append(f"[b {status_color}]{status}[/] [b {MCP_COLOR}]{escape(server_name)}[/] [{len(tool_names)}]")
            for tname in tool_names:
                lines.append(f"  [b {MCP_COLOR}]  └ {escape(tname)}[/]")
        return "\n".join(lines)

    def _status_markup(self) -> str:
        if self._agent.compacting:
            return "[yellow]◐ 正在压缩上下文…[/]"
        if self._busy:
            return "[yellow]◐ 思考中…[/]"
        if self._agent.input_blocked:
            threshold = int((self._settings.agent.compact_threshold if self._settings else 0.8) * 100)
            return f"[#f85149]● 上下文已达 {threshold}%，请输入 /compact 压缩后继续[/]"
        mcp_info = ""
        if self._mcp_adapter:
            mcp_count = sum(len(v) for v in self._mcp_adapter._server_tools.values())
            if mcp_count:
                mcp_info = f"  [{MCP_COLOR}]· {mcp_count} MCP[/]"
        return f"[{TOOL_COLOR}]● 就绪[/]  [{MUTED}]· {escape(self._model)} · {len(self._all_tools)} 工具{mcp_info}[/]"

    # ---------- 消息渲染 ----------

    def _welcome(self) -> None:
        hint_lines = [
            "输入问题开始对话。",
            "输入 [bold #58a6ff]/help[/] 查看所有斜杠命令。",
            "输入 [bold #58a6ff]/[/] 查看命令补全。",
        ]
        if self._agent.agents_md_loaded:
            hint_lines.append("[bold #3fb950]AGENTS.md[/] 已加载")
        self._write(Panel(
            Text.from_markup("\n".join(hint_lines), style=MUTED),
            title="aAgent", title_align="left", border_style="#30363d", padding=(0, 1), expand=True,
        ))

    def _user_panel(self, text: str) -> Panel:
        return Panel(
            Text(text, style="#e6edf3"),
            title="你", title_align="left", border_style=USER_COLOR, padding=(0, 1), expand=True,
        )

    def _ai_panel(self, text: str) -> Panel:
        cleaned = _clean_latex(text) if text else text
        return Panel(
            Markdown(cleaned) if cleaned else Text("(空回复)", style=MUTED),
            title="aAgent", title_align="left", border_style=AI_COLOR, padding=(0, 1), expand=True,
        )

    def _tool_panel(self, name: str, args: dict, result: str, elapsed: float) -> Panel:
        preview = result if len(result) <= 600 else result[:600] + f"\n…（共 {len(result)} 字，已截断）"
        body = Group(
            Text("参数", style=f"bold {MUTED}"),
            JSON(json.dumps(args, ensure_ascii=False, indent=2)),
            Text(""),
            Text("结果", style=f"bold {MUTED}"),
            Text(preview, style="#c9d1d9"),
        )
        is_mcp = name.startswith("mcp_")
        title_prefix = "⚙ " + ("MCP " if is_mcp else "")
        border = MCP_COLOR if is_mcp else TOOL_COLOR
        return Panel(
            body,
            title=f"{title_prefix}{name} · {elapsed * 1000:.0f} ms", title_align="left",
            border_style=border, padding=(0, 1), expand=True,
        )

    def _write(self, renderable) -> None:
        log = self.query_one("#log", RichLog)
        log.write(renderable)
        log.write(Text(""))

    # ==============================================================
    #               内嵌面板（slash-panel / session-panel）
    # ==============================================================

    # ---- 斜杠命令面板 ----

    @property
    def slash_panel_open(self) -> bool:
        """斜杠补全面板是否打开（供输入框判断 Tab 用途）。"""
        return self._panel_open == "slash"

    def _show_slash_panel(self, filter_str: str = "") -> None:
        """显示斜杠命令补全面板（通过加 .open class）。"""
        self._panel_open = "slash"
        self._slash_filter_input = "/" + filter_str
        self._slash_filter = filter_str.lower()
        self._slash_selected = 0
        self.query_one("#slash-panel").add_class("open")
        self._refresh_slash_panel()

    def _hide_slash_panel(self) -> None:
        """隐藏斜杠命令补全面板。"""
        self._panel_open = None
        self.query_one("#slash-panel").remove_class("open")

    def _filtered_slash_cmds(self) -> List[str]:
        if not self._slash_filter:
            return list(SLASH_COMMANDS.keys())
        f = self._slash_filter
        return [
            n for n in SLASH_COMMANDS.keys()
            if f in n or f in SLASH_COMMANDS[n]["desc"].lower()
        ]

    def _refresh_slash_panel(self) -> None:
        cmds = self._filtered_slash_cmds()
        if self._slash_selected >= len(cmds):
            self._slash_selected = max(0, len(cmds) - 1)

        # Header
        self.query_one("#sp-title", Static).update("[bold #58a6ff]斜杠命令[/]")
        if self._slash_filter:
            self.query_one("#sp-filter", Static).update(
                f"  [dim]过滤:[/] [bold #f0883e]{escape(self._slash_filter)}[/]  "
            )
        else:
            self.query_one("#sp-filter", Static).update("  ")
        self.query_one("#sp-count", Static).update(f"[#484f58]─ {len(cmds)} 项[/]")

        # List — Text.assemble 避开 markup 嵌套
        result = Text()
        if not cmds:
            result.append("  无匹配命令", "#484f58")
        else:
            for i, cmd in enumerate(cmds):
                info = SLASH_COMMANDS[cmd]
                name = cmd.ljust(12)
                desc = info["desc"]
                if i > 0:
                    result.append("\n")
                if i == self._slash_selected:
                    result.append_text(Text.assemble(
                        ("  ▶ ", "#c9d1d9 on #1f6feb bold"),
                        (name, "#c9d1d9 on #1f6feb bold"),
                        (" ", "#c9d1d9 on #1f6feb"),
                        (desc, "#8b949e on #1f6feb"),
                    ))
                else:
                    result.append_text(Text.assemble(
                        ("  ", "#c9d1d9"),
                        (name, "#58a6ff bold"),
                        (" ", "#c9d1d9"),
                        (desc, "#8b949e dim"),
                    ))
        self.query_one("#sp-list", Static).update(result)
        self.query_one("#sp-hint", Static).update(
            "[dim]↑↓ 选择  Tab 补全  Enter 执行  ESC 取消[/]"
        )

    @on(TextArea.Changed, "#prompt")
    def _on_prompt_changed(self, event: TextArea.Changed) -> None:
        """监听输入框文本变化，以 '/' 开头时打开/更新面板；否则关闭。"""
        if self._busy:
            return
        text = event.control.text.strip()

        if text.startswith("/"):
            filter_str = text.lstrip("/")
            if self._panel_open != "slash":
                self._show_slash_panel(filter_str)
            else:
                # 面板已打开，更新过滤
                self._slash_filter_input = text
                self._slash_filter = filter_str.lower()
                self._slash_selected = 0
                self._refresh_slash_panel()
        else:
            if self._panel_open == "slash":
                self._hide_slash_panel()

    @on(PromptArea.ComplementRequested)
    def _on_complement_requested(self, event: PromptArea.ComplementRequested) -> None:
        """Tab 补全：把输入框补到候选命令的公共前缀。"""
        prompt = self.query_one("#prompt", PromptArea)
        cmds = self._filtered_slash_cmds()
        if not cmds:
            return
        current = prompt.text.strip()
        # 优先只按命令名前缀匹配补全，避免描述命中造成的干扰
        prefix_cmds = [c for c in cmds if c.startswith(current)]
        candidates = prefix_cmds or cmds
        common = _common_prefix(candidates)
        if len(common) <= len(current):
            return
        prompt.load_text(common)
        prompt.move_cursor((0, len(common)))

    # ---- 会话列表面板 ----

    def _show_session_panel(self) -> None:
        """显示会话恢复面板。"""
        if not self._session_mgr:
            return
        sessions = self._session_mgr.list_sessions()
        if not sessions:
            self._write(Panel(
                Text("暂无历史会话。", style=MUTED),
                title="/resume", title_align="left", border_style="#30363d", padding=(0, 1), expand=True,
            ))
            return
        self._session_list = list(sessions)
        self._session_selected = 0
        self._panel_open = "session"
        self.query_one("#session-panel").add_class("open")
        self._refresh_session_panel()

    def _hide_session_panel(self) -> None:
        self._panel_open = None
        self.query_one("#session-panel").remove_class("open")

    def _refresh_session_panel(self) -> None:
        sessions = self._session_list
        self.query_one("#ss-title", Static).update("[bold #3fb950]历史会话[/]  ")
        self.query_one("#ss-count", Static).update(f"[#484f58]─ {len(sessions)} 项[/]")

        result = Text()
        if not sessions:
            result.append("  暂无历史会话", "#484f58")
        else:
            for i, s in enumerate(sessions):
                sid = s["session_id"]
                first_msg = s.get("first_user_msg", "(无)")[:40]
                turns = s["turns"]
                msgs = s["message_count"]
                saved_at = s.get("saved_at", "")
                if i > 0:
                    result.append("\n")
                if i == self._session_selected:
                    result.append_text(Text.assemble(
                        ("  ▶ ", "#c9d1d9 on #1f6feb bold"),
                        (sid, "#c9d1d9 on #1f6feb bold"),
                        (" ", "#c9d1d9 on #1f6feb"),
                        (first_msg, "#8b949e on #1f6feb"),
                    ))
                    result.append("\n")
                    result.append_text(Text.assemble(
                        ("    ", "#c9d1d9 on #1f6feb"),
                        (f"{turns}轮 · {msgs}消息 · 保存于 {saved_at}", "#8b949e on #1f6feb dim"),
                    ))
                else:
                    result.append_text(Text.assemble(
                        ("  ", "#c9d1d9"),
                        (sid, "#58a6ff bold"),
                        (" ", "#c9d1d9"),
                        (first_msg, "#8b949e"),
                    ))
                    result.append("\n")
                    result.append_text(Text.assemble(
                        ("    ", "#c9d1d9"),
                        (f"{turns}轮 · {msgs}消息 · 保存于 {saved_at}", "#484f58 dim"),
                    ))
        self.query_one("#ss-list", Static).update(result)
        self.query_one("#ss-hint", Static).update(
            "[dim]↑↓ 选择  Enter 恢复  d 删除  ESC 取消[/dim]"
        )

    # ---- 键盘拦截（App 级，面板打开时吃掉按键） ----

    async def _on_key(self, event: Key) -> None:
        """面板打开时，在 App 层拦截键盘事件。"""
        if self._panel_open is None:
            # 无面板，交回 App 默认处理（含全局快捷键绑定）
            await super()._on_key(event)
            return

        key = event.key
        prompt = self.query_one("#prompt", PromptArea)

        if key == "escape":
            event.prevent_default(); event.stop()
            if self._panel_open == "slash":
                self._hide_slash_panel()
                prompt.clear()
            else:
                self._hide_session_panel()
                prompt.focus()
            return

        if self._panel_open == "slash":
            if key == "enter":
                event.prevent_default(); event.stop()
                cmds = self._filtered_slash_cmds()
                if cmds:
                    cmd_name = cmds[self._slash_selected]
                    self._hide_slash_panel()
                    prompt.clear()
                    self._handle_slash_command(cmd_name)
                return
            if key in ("up", "k"):
                event.prevent_default(); event.stop()
                cmds = self._filtered_slash_cmds()
                if cmds:
                    self._slash_selected = (self._slash_selected - 1) % len(cmds)
                    self._refresh_slash_panel()
                return
            if key in ("down", "j"):
                event.prevent_default(); event.stop()
                cmds = self._filtered_slash_cmds()
                if cmds:
                    self._slash_selected = (self._slash_selected + 1) % len(cmds)
                    self._refresh_slash_panel()
                return
            # 退格/可打印字符交给 TextArea（会触发 TextArea.Changed → 自动更新过滤）
            return

        if self._panel_open == "session":
            if key == "enter":
                event.prevent_default(); event.stop()
                if self._session_list:
                    sid = self._session_list[self._session_selected]["session_id"]
                    self._hide_session_panel()
                    self._load_session_by_id(sid)
                return
            if key == "d":
                event.prevent_default(); event.stop()
                if self._session_list and self._session_mgr:
                    sid = self._session_list[self._session_selected]["session_id"]
                    self._session_mgr.delete_session(sid)
                    self._session_list.pop(self._session_selected)
                    if self._session_selected >= len(self._session_list):
                        self._session_selected = max(0, len(self._session_list) - 1)
                    if not self._session_list:
                        self._hide_session_panel()
                    else:
                        self._refresh_session_panel()
                return
            if key in ("up", "k"):
                event.prevent_default(); event.stop()
                if self._session_list:
                    self._session_selected = (self._session_selected - 1) % len(self._session_list)
                    self._refresh_session_panel()
                return
            if key in ("down", "j"):
                event.prevent_default(); event.stop()
                if self._session_list:
                    self._session_selected = (self._session_selected + 1) % len(self._session_list)
                    self._refresh_session_panel()
                return
            return

    # ==============================================================
    #                      交互：提交
    # ==============================================================

    def _submit_prompt(self) -> None:
        if self._busy:
            return
        textarea = self.query_one("#prompt", PromptArea)
        text = textarea.text.strip()
        if not text:
            return

        # 斜杠命令直接在输入框输入执行
        if text.startswith("/"):
            textarea.clear()
            self._hide_slash_panel()
            self._handle_slash_command(text)
            return

        if self._agent.input_blocked:
            threshold = int((self._settings.agent.compact_threshold if self._settings else 0.8) * 100)
            self._write(Panel(
                Text(f"上下文已达 {threshold}% 阈值，新的提问已暂停。\n请输入 /compact 压缩上下文后再继续。", style="yellow"),
                title="已暂停输入", title_align="left", border_style="yellow", padding=(0, 1), expand=True,
            ))
            return

        textarea.clear()
        self._turns += 1
        self._write(self._user_panel(text))
        self._set_busy(True)
        self._ask(text)

    @on(PromptArea.SubmitRequested, "#prompt")
    def _on_submit(self, event: PromptArea.SubmitRequested) -> None:
        self._submit_prompt()

    @on(Button.Pressed, "#send-btn")
    def _on_send_pressed(self) -> None:
        self._submit_prompt()

    @work(thread=True, exclusive=True)
    def _ask(self, text: str) -> None:
        try:
            answer = self._agent.send(text, on_tool=self._on_tool)
            panel = self._ai_panel(answer)
        except Exception as exc:
            panel = Panel(
                Text(f"{type(exc).__name__}: {exc}", style="red"),
                title="调用失败", title_align="left", border_style="red", padding=(0, 1), expand=True,
            )
        self.call_from_thread(self._finish, panel)

    def _on_tool(self, name: str, args: dict, result: str, elapsed: float) -> None:
        self.call_from_thread(self._write, self._tool_panel(name, args, result, elapsed))

    # ==============================================================
    #                     斜杠命令处理器
    # ==============================================================

    def _handle_slash_command(self, command: str) -> None:
        parts = command.split(maxsplit=1)
        cmd_name = parts[0].lower()
        cmd_arg = parts[1] if len(parts) > 1 else ""

        info = SLASH_COMMANDS.get(cmd_name)
        if info is None:
            self._write(Panel(
                Text(f"未知命令: {command}\n输入 /help 查看所有可用命令。", style="yellow"),
                title="命令错误", title_align="left", border_style="yellow", padding=(0, 1), expand=True,
            ))
            return

        handler_name = info["handler"]
        handler = getattr(self, handler_name, None)
        if handler:
            handler(cmd_arg)
        else:
            self._write(Panel(
                Text(f"命令处理器缺失: {handler_name}", style="red"),
                title="内部错误", title_align="left", border_style="red", padding=(0, 1), expand=True,
            ))

    # ---- /help ----

    def cmd_help(self, arg: str = "") -> None:
        lines = ["[b]可用斜杠命令[/b]"]
        for name, info in SLASH_COMMANDS.items():
            lines.append(f"  [b #58a6ff]{escape(name.ljust(12))}[/] [dim]{escape(info['desc'])}[/]")
        lines.append("")
        lines.append("[b]快捷键[/b]")
        for binding in self.BINDINGS:
            lines.append(f"  [b #58a6ff]{escape(binding[0].upper().ljust(15))}[/] [dim]{escape(binding[2])}[/]")
        self._write(Panel(
            Text.from_markup("\n".join(lines)),
            title="帮助", title_align="left", border_style="#4a9eff", padding=(0, 1), expand=True,
        ))

    # ---- /new ----

    def cmd_new_session(self, arg: str = "") -> None:
        if self._busy:
            self._write(Panel(
                Text("请等待当前请求完成后再新建会话。", style="yellow"),
                title="提示", title_align="left", border_style="yellow", padding=(0, 1), expand=True,
            ))
            return
        self._auto_save()
        self._agent.reset()
        self._turns = 0
        self._session_id = uuid.uuid4().hex[:8]
        self._all_tools = list(self._local_tools)
        self.query_one("#log", RichLog).clear()
        self._refresh_sidebar()
        self._write(Panel(
            Text(f"已保存会话，开始新会话 ID: {self._session_id}", style=TOOL_COLOR),
            title="/new", title_align="left", border_style=TOOL_COLOR, padding=(0, 1), expand=True,
        ))
        self._welcome()

    # ---- /resume ----

    def cmd_resume_session(self, arg: str = "") -> None:
        if self._busy:
            self._write(Panel(
                Text("请等待当前请求完成后再恢复会话。", style="yellow"),
                title="提示", title_align="left", border_style="yellow", padding=(0, 1), expand=True,
            ))
            return
        self._auto_save()

        if arg:
            self._load_session_by_id(arg)
            return

        # 使用内嵌 session-panel widget
        self._show_session_panel()

    def _load_session_by_id(self, session_id: str) -> None:
        if not self._session_mgr:
            return
        data = self._session_mgr.load_session(session_id)
        if data is None:
            self._write(Panel(
                Text(f"未找到会话: {session_id}", style="red"),
                title="/resume", title_align="left", border_style="red", padding=(0, 1), expand=True,
            ))
            return

        messages = data.get("messages", [])
        turns = data.get("turns", len([m for m in messages if m.get("role") in ("user", "assistant")]) // 2)
        agents_md_loaded = data.get("agents_md_loaded", False)

        self._agent.load_messages(messages, agents_md_loaded=agents_md_loaded)
        self._session_id = data.get("session_id", session_id)
        self._turns = turns
        self._all_tools = list(self._local_tools)
        self.query_one("#log", RichLog).clear()
        self._refresh_sidebar()

        self._write(Panel(
            Text(f"已恢复会话 {self._session_id}（{turns} 轮，{len(messages)} 条消息）", style=TOOL_COLOR),
            title="/resume", title_align="left", border_style=TOOL_COLOR, padding=(0, 1), expand=True,
        ))

    # ---- /save ----

    def cmd_save_session(self, arg: str = "") -> None:
        if not self._session_mgr:
            self._write(Panel(
                Text("会话管理未初始化。", style="red"),
                title="错误", title_align="left", border_style="red", padding=(0, 1), expand=True,
            ))
            return
        path = self._session_mgr.save_session(
            self._session_id,
            self._agent.messages,
            self._turns,
            agents_md_loaded=self._agent.agents_md_loaded,
        )
        self._write(Panel(
            Text(f"已保存会话 {self._session_id}\n路径: {path}", style=TOOL_COLOR),
            title="/save", title_align="left", border_style=TOOL_COLOR, padding=(0, 1), expand=True,
        ))

    # ---- /quit ----

    def cmd_quit(self, arg: str = "") -> None:
        self._auto_save()
        self.exit()

    # ---- /compact ----

    def cmd_compact(self, arg: str = "") -> None:
        self._turns += 1
        self._write(self._user_panel("/compact"))
        self._set_busy(True)
        self._compact_worker()

    @work(thread=True, exclusive=True)
    def _compact_worker(self) -> None:
        try:
            archive_id = self._agent.compact()
            panel = Panel(
                Text(
                    f"上下文压缩完成，归档编号：{archive_id}\n"
                    f"原始上下文已保存到 .agents/context/{archive_id}.jsonl，"
                    f"后续可通过 recallContext 工具检索。",
                    style=TOOL_COLOR,
                ),
                title="压缩完成", title_align="left", border_style=TOOL_COLOR, padding=(0, 1), expand=True,
            )
        except Exception as exc:
            panel = Panel(
                Text(f"{type(exc).__name__}: {exc}\n原有上下文未改动，可重新执行 /compact。", style="red"),
                title="压缩失败", title_align="left", border_style="red", padding=(0, 1), expand=True,
            )
        self.call_from_thread(self._finish, panel)

    # ---- /clear ----

    def cmd_clear(self, arg: str = "") -> None:
        self.query_one("#log", RichLog).clear()

    # ---- /tools ----

    def cmd_tools(self, arg: str = "") -> None:
        lines = [f"[b]本地工具 · {len(self._local_tools)}[/]"]
        for t in self._local_tools:
            lines.append(f"  [b #3fb950]{escape(t['name'])}[/]")
            lines.append(f"    [dim]{escape(t['description'])}[/]")

        mcp_count = self._mcp_tool_count()
        lines.append("")
        lines.append(f"[b]MCP 工具 · {mcp_count}[/]")
        if self._mcp_adapter:
            for server_name, tool_names in self._mcp_adapter._server_tools.items():
                lines.append(f"  [b #bc8cff]{escape(server_name)}[/]")
                for tname in tool_names:
                    lines.append(f"    [b #bc8cff]  └ {escape(tname)}[/]")
        else:
            lines.append("  [dim]无[/]")

        self._write(Panel(
            Text.from_markup("\n".join(lines)),
            title="/tools", title_align="left", border_style="#4a9eff", padding=(0, 1), expand=True,
        ))

    # ---- /status ----

    def cmd_status(self, arg: str = "") -> None:
        used, window, ratio, is_default = self._agent.context_stats()
        lines = [
            f"[b]会话 ID[/]       {self._session_id}",
            f"[b]已用轮次[/]     {self._turns}",
            f"[b]消息数[/]       {len(self._agent.messages)}",
            f"[b]上下文用量[/]   {used / 1000:.1f}k / {window / 1000:.0f}k ({ratio * 100:.1f}%)",
            f"[b]上下文阈值[/]   {int((self._settings.agent.compact_threshold if self._settings else 0.8) * 100)}%",
            f"[b]AGENTS.md[/]    {'已加载' if self._agent.agents_md_loaded else '未加载'}",
            f"[b]本地工具[/]     {len(self._local_tools)}",
            f"[b]MCP 工具[/]     {self._mcp_tool_count()}",
            f"[b]状态[/]         {'思考中' if self._busy else ('已压缩进行中' if self._agent.compacting else ('已达阈值，请压缩' if self._agent.input_blocked else '就绪'))}",
        ]
        self._write(Panel(
            Text.from_markup("\n".join(lines)),
            title="/status", title_align="left", border_style="#4a9eff", padding=(0, 1), expand=True,
        ))

    # ==============================================================
    #                       自动保存 & Finish
    # ==============================================================

    def _auto_save(self) -> None:
        if self._session_mgr and self._settings and self._settings.session.auto_save:
            try:
                self._session_mgr.save_session(
                    self._session_id,
                    self._agent.messages,
                    self._turns,
                    agents_md_loaded=self._agent.agents_md_loaded,
                )
            except Exception:
                pass

    def _finish(self, panel: Panel) -> None:
        self._write(panel)
        self._set_busy(False)
        self._auto_save()
        if self._agent.input_blocked:
            threshold = int((self._settings.agent.compact_threshold if self._settings else 0.8) * 100)
            self._write(Panel(
                Text(f"上下文使用量已达 {threshold}% 阈值，新的提问已暂停。\n请输入 /compact 压缩上下文后再继续。", style="yellow"),
                title="上下文警告", title_align="left", border_style="yellow", padding=(0, 1), expand=True,
            ))

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        textarea = self.query_one("#prompt", TextArea)
        textarea.disabled = busy
        spinner_widget = self.query_one("#spinner", Static)
        if not busy:
            spinner_widget.update("")
        self._refresh_sidebar()
        if not busy:
            textarea.focus()

    # ---------- 快捷键 ----------

    def action_clear_log(self) -> None:
        self.query_one("#log", RichLog).clear()

    def action_new_session(self) -> None:
        self.cmd_new_session()

    def action_save_session(self) -> None:
        self.cmd_save_session()

    def action_resume_session(self) -> None:
        self.cmd_resume_session()

    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one("#sidebar")
        sidebar.display = not sidebar.display
