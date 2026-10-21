"""终端界面（Textual）：只负责输入、展示与线程调度，业务逻辑全部来自 core。"""
import json
import uuid
from typing import List, Optional

from rich.console import Group
from rich.json import JSON
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Input, RichLog, Static

from core.agent import Agent

USER_COLOR = "#58a6ff"
AI_COLOR = "#1f6feb"
TOOL_COLOR = "#3fb950"
MUTED = "#8b949e"


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
        width: 40; background: #11161d; border-left: solid #30363d; padding: 0 1;
    }
    #session { height: auto; padding: 0 0 1 0; }
    #tools { height: auto; }
    #status { height: 1; background: #161b22; color: #8b949e; padding: 0 1; }
    #prompt { margin: 0 1 1 1; border: round #4a9eff; background: #0d1117; }
    #prompt:focus { border: round #58a6ff; }
    """

    BINDINGS = [
        ("ctrl+q", "quit", "退出"),
        ("ctrl+n", "new_session", "新会话"),
        ("ctrl+l", "clear_log", "清屏"),
        ("ctrl+b", "toggle_sidebar", "侧栏"),
    ]

    def __init__(
        self,
        agent: Agent,
        model: str = "",
        base_url: str = "",
        workspace: str = "",
        tools: Optional[List[dict]] = None,
    ) -> None:
        super().__init__()
        self._agent = agent
        self._model = model
        self._base_url = base_url
        self._workspace = workspace
        self._tools = tools or []
        self._session_id = uuid.uuid4().hex[:8]
        self._turns = 0
        self._busy = False
        self.title = "aAgent"
        self.sub_title = model

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="main"):
                yield Static(self._banner_markup(), id="info")
                yield RichLog(id="log", markup=False, wrap=True)
            with VerticalScroll(id="sidebar"):
                yield Static(self._session_markup(), id="session")
                yield Static(self._tools_markup(), id="tools")
        yield Static(self._status_markup(), id="status")
        yield Input(placeholder="输入问题后回车发送…", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        self._set_busy(False)
        self._welcome()

    # ---------- 布局文本 ----------

    def _banner_markup(self) -> str:
        return (
            f"[b {USER_COLOR}]aAgent[/]  [dim]·[/]  "
            f"[b {TOOL_COLOR}]{len(self._tools)}[/] 个工具  [dim]·[/]  {escape(self._model)}\n"
            f"[{MUTED}]工作区[/]  {escape(self._workspace)}\n"
            f"[{MUTED}]Enter 发送   Ctrl+N 新会话   Ctrl+L 清屏   Ctrl+B 侧栏   Ctrl+Q 退出[/]"
        )

    def _session_markup(self) -> str:
        state = f"[yellow]思考中[/]" if self._busy else f"[{TOOL_COLOR}]就绪[/]"
        return (
            f"[b]会话[/]\n"
            f"[{MUTED}]模型[/]    {escape(self._model)}\n"
            f"[{MUTED}]接口[/]    {escape(self._base_url)}\n"
            f"[{MUTED}]工作区[/]  {escape(self._workspace)}\n"
            f"[{MUTED}]会话ID[/]  {self._session_id}\n"
            f"[{MUTED}]轮次[/]    {self._turns}\n"
            f"[{MUTED}]消息[/]    {len(self._agent.messages)}\n"
            f"[{MUTED}]状态[/]    {state}"
        )

    def _tools_markup(self) -> str:
        lines = [f"[b]工具 · {len(self._tools)}[/]"]
        for tool in self._tools:
            lines.append(f"[b {TOOL_COLOR}]• {escape(tool['name'])}[/]")
            lines.append(f"[{MUTED}]{escape(tool['description'])}[/]")
        return "\n".join(lines)

    def _status_markup(self) -> str:
        if self._busy:
            return "[yellow]◐ 思考中…[/]"
        return f"[{TOOL_COLOR}]● 就绪[/]  [{MUTED}]· {escape(self._model)} · {len(self._tools)} 个工具[/]"

    # ---------- 消息渲染 ----------

    def _welcome(self) -> None:
        self._write(Panel(
            Text("输入问题开始对话。可查询日期时间、判断闰年，以及读写工作区文件。", style=MUTED),
            title="aAgent", title_align="left", border_style="#30363d", padding=(0, 1), expand=True,
        ))

    def _user_panel(self, text: str) -> Panel:
        return Panel(
            Text(text, style="#e6edf3"),
            title="你", title_align="left", border_style=USER_COLOR, padding=(0, 1), expand=True,
        )

    def _ai_panel(self, text: str) -> Panel:
        return Panel(
            Markdown(text) if text else Text("(空回复)", style=MUTED),
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
        return Panel(
            body,
            title=f"⚙ {name} · {elapsed * 1000:.0f} ms", title_align="left",
            border_style=TOOL_COLOR, padding=(0, 1), expand=True,
        )

    def _write(self, renderable) -> None:
        log = self.query_one("#log", RichLog)
        log.write(renderable)
        log.write(Text(""))

    # ---------- 交互 ----------

    @on(Input.Submitted, "#prompt")
    def _on_submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text or self._busy:
            return
        event.input.value = ""
        self._turns += 1
        self._write(self._user_panel(text))
        self._set_busy(True)
        self._ask(text)

    @work(thread=True, exclusive=True)
    def _ask(self, text: str) -> None:
        """在后台线程调用 core，避免阻塞界面。"""
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

    def _finish(self, panel: Panel) -> None:
        self._write(panel)
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        prompt = self.query_one("#prompt", Input)
        prompt.disabled = busy
        self.query_one("#status", Static).update(self._status_markup())
        self.query_one("#session", Static).update(self._session_markup())
        if not busy:
            prompt.focus()

    # ---------- 快捷键 ----------

    def action_clear_log(self) -> None:
        self.query_one("#log", RichLog).clear()

    def action_new_session(self) -> None:
        if self._busy:
            return
        self._agent.reset()
        self._turns = 0
        self._session_id = uuid.uuid4().hex[:8]
        self.query_one("#log", RichLog).clear()
        self.query_one("#session", Static).update(self._session_markup())
        self._welcome()

    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one("#sidebar")
        sidebar.display = not sidebar.display
