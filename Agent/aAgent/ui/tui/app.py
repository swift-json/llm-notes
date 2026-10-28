"""终端界面（Textual）：只负责输入、展示与线程调度，业务逻辑全部来自 core。"""
import json
import sys
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
from textual.events import Key
from textual.message import Message
from textual.widgets import Button, Footer, Header, RichLog, Static, TextArea

from core.agent import Agent

USER_COLOR = "#58a6ff"
AI_COLOR = "#1f6feb"
TOOL_COLOR = "#3fb950"
MUTED = "#8b949e"

# Spinner frames，每 ~120ms 切换一帧
_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class PromptArea(TextArea):
    """多行输入框：Enter 发送，Ctrl+J / Shift+Enter 换行。

    大部分 Windows 终端无法把 Ctrl+Enter / Alt+Enter 与 Enter 区分，
    因此 Enter 直接发送；Ctrl+J（LF）在所有终端都能被正确识别为换行。
    """

    class SubmitRequested(Message):
        """用户请求发送消息。"""

        def __init__(self, text: str, control: "PromptArea") -> None:
            super().__init__()
            self.text = text
            self._control = control

        @property
        def control(self) -> "PromptArea":
            return self._control

    def _on_key(self, event: Key) -> None:
        key = event.key
        if key == "enter" or (key.endswith("+enter") and not key.startswith("shift+")):
            # Enter / Ctrl+Enter / Alt+Enter → 发送
            event.prevent_default()
            event.stop()
            self.post_message(self.SubmitRequested(self.text, self))
            return
        if key == "ctrl+j" or key == "shift+enter":
            # 换行
            event.prevent_default()
            event.stop()
            start, end = self.selection
            self._replace_via_keyboard("\n", start, end)
            return
        super()._on_key(event)


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
        self._spin_idx = 0
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
        with Horizontal(id="prompt-wrap"):
            yield Static("", id="spinner")
            with Vertical(id="prompt-box"):
                yield PromptArea(
                    placeholder="输入问题，Enter 发送，Ctrl+J 换行…",
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
        # 开启 spinner 定时刷新（每 120ms 换一帧）
        self.set_interval(0.12, self._tick_spinner)
        # 隐藏 Textual 自绘方块光标，改用终端原生竖杠光标
        pa = self.query_one("#prompt", TextArea)
        pa.show_cursor = False
        sys.stdout.write("\x1b[5 q")  # DECSCUSR: 闪烁竖杠光标
        sys.stdout.flush()

    def on_unmount(self) -> None:
        """退出时恢复终端光标（如果之前改过）。"""
        sys.stdout.write("\x1b[2 q")
        sys.stdout.flush()

    # ---------- Spinner 动画 ----------

    def _tick_spinner(self) -> None:
        if not self._busy:
            return
        self._spin_idx = (self._spin_idx + 1) % len(_SPINNER_FRAMES)
        spinner_widget = self.query_one("#spinner", Static)
        spinner_widget.update(_SPINNER_FRAMES[self._spin_idx])

    # ---------- 布局文本 ----------

    def _banner_markup(self) -> str:
        return (
            f"[b {USER_COLOR}]aAgent[/]  [dim]·[/]  "
            f"[b {TOOL_COLOR}]{len(self._tools)}[/] 个工具  [dim]·[/]  {escape(self._model)}\n"
            f"[{MUTED}]工作区[/]  {escape(self._workspace)}\n"
            f"[{MUTED}]Enter 发送   Ctrl+J 换行   Ctrl+N 新会话   Ctrl+L 清屏   Ctrl+B 侧栏   Ctrl+Q 退出[/]"
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

    def _submit_prompt(self) -> None:
        """发送当前输入（Enter / Ctrl+Enter / 点击按钮共用）。"""
        if self._busy:
            return
        textarea = self.query_one("#prompt", PromptArea)
        text = textarea.text.strip()
        if not text:
            return
        textarea.clear()
        self._turns += 1
        self._write(self._user_panel(text))
        self._set_busy(True)
        self._ask(text)

    @on(PromptArea.SubmitRequested, "#prompt")
    def _on_submit(self, event: PromptArea.SubmitRequested) -> None:
        """Enter 键触发发送。"""
        self._submit_prompt()

    @on(Button.Pressed, "#send-btn")
    def _on_send_pressed(self) -> None:
        """点击右下角 ↑ 按钮 = 发送。"""
        self._submit_prompt()

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
        textarea = self.query_one("#prompt", TextArea)
        textarea.disabled = busy
        # spinner：空闲时清空，忙碌时由 _tick_spinner 填充
        spinner_widget = self.query_one("#spinner", Static)
        if not busy:
            spinner_widget.update("")
        self.query_one("#status", Static).update(self._status_markup())
        self.query_one("#session", Static).update(self._session_markup())
        if not busy:
            textarea.focus()

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
