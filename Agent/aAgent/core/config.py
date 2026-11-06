"""应用配置：从 config.ini 读取，供任意界面层复用。

配置优先级：config.ini 显式值 > 默认值常量
所有硬编码参数统一在此文件定义默认值，方便集中管理。
"""
from dataclasses import dataclass, field
from pathlib import Path
import configparser
from typing import List, Optional

# ============== 默认值常量 ==============

# LLM 默认配置
DEFAULT_CONTEXT_WINDOW = 128000
DEFAULT_LLM_TIMEOUT = 60.0
DEFAULT_TEMPERATURE = 0.7

# MCP 默认配置
DEFAULT_MCP_CONNECT_TIMEOUT = 30.0
DEFAULT_MCP_CALL_TIMEOUT = 30.0
DEFAULT_MCP_DISCONNECT_TIMEOUT = 5.0
DEFAULT_MCP_DISCOVERY_RETRY = 1

# 会话管理默认配置
DEFAULT_SESSION_DIR = ".agents/sessions"
DEFAULT_SESSION_AUTO_SAVE = True

# 上下文压缩阈值（达到后暂停接受普通输入）
DEFAULT_COMPACT_THRESHOLD = 0.8

# Agent 默认配置
DEFAULT_SYSTEM_PROMPT = ""

# 搜索默认配置
DEFAULT_SEARCH_BASE_URL = "https://qianfan.baidubce.com/v2/ai_search"

# UI 默认配置
DEFAULT_SPINNER_INTERVAL = 0.12
DEFAULT_SIDEBAR_WIDTH = 40

# 工具级默认配置
DEFAULT_FETCH_TIMEOUT = 20
DEFAULT_SEARCH_TIMEOUT = 15
DEFAULT_MAX_CONTENT_CHARS = 8000


# ============== 数据类 ==============

@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    context_window: int = DEFAULT_CONTEXT_WINDOW
    context_window_is_default: bool = True
    timeout: float = DEFAULT_LLM_TIMEOUT
    temperature: float = DEFAULT_TEMPERATURE


@dataclass(frozen=True)
class SearchConfig:
    api_key: str
    base_url: str = DEFAULT_SEARCH_BASE_URL


@dataclass(frozen=True)
class MCPConfig:
    """MCP 相关配置。"""
    connect_timeout: float = DEFAULT_MCP_CONNECT_TIMEOUT
    call_timeout: float = DEFAULT_MCP_CALL_TIMEOUT
    disconnect_timeout: float = DEFAULT_MCP_DISCONNECT_TIMEOUT
    async_load: bool = True  # 是否异步加载 MCP（先入 TUI 后加载）


@dataclass(frozen=True)
class SessionConfig:
    """会话持久化配置。"""
    session_dir: str = DEFAULT_SESSION_DIR
    auto_save: bool = DEFAULT_SESSION_AUTO_SAVE


@dataclass(frozen=True)
class AgentConfig:
    """Agent 核心行为配置。"""
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    compact_threshold: float = DEFAULT_COMPACT_THRESHOLD


@dataclass(frozen=True)
class UIConfig:
    """TUI 界面配置。"""
    spinner_interval: float = DEFAULT_SPINNER_INTERVAL
    sidebar_width: int = DEFAULT_SIDEBAR_WIDTH


@dataclass(frozen=True)
class Settings:
    llm: LLMConfig
    workspace_root: str
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    search: Optional[SearchConfig] = None
    mcp: MCPConfig = field(default_factory=MCPConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    ui: UIConfig = field(default_factory=UIConfig)


# ============== 加载逻辑 ==============

def load_settings(config_path: Path) -> Settings:
    """从 config.ini 加载完整配置。"""
    config_path = Path(config_path).resolve()
    cfg = configparser.ConfigParser()
    cfg.read(config_path, encoding="utf-8")

    # ---- [llm] 节 ----
    window_raw = cfg.get("llm", "context_window", fallback="").strip()
    llm = LLMConfig(
        base_url=cfg["llm"]["base_url"],
        api_key=cfg["llm"]["api_key"],
        model=cfg["llm"]["model"],
        context_window=int(window_raw) if window_raw else DEFAULT_CONTEXT_WINDOW,
        context_window_is_default=not window_raw,
        timeout=cfg.getfloat("llm", "timeout", fallback=DEFAULT_LLM_TIMEOUT),
        temperature=cfg.getfloat("llm", "temperature", fallback=DEFAULT_TEMPERATURE),
    )

    # ---- [agent] 节 ----
    workspace_root = cfg.get("agent", "workspace_root", fallback=str(config_path.parents[2]))
    system_prompt = cfg.get("agent", "system_prompt", fallback=DEFAULT_SYSTEM_PROMPT)
    compact_threshold = cfg.getfloat("agent", "compact_threshold", fallback=DEFAULT_COMPACT_THRESHOLD)

    # ---- [search] 节 ----
    search = None
    if cfg.has_section("search") and cfg.has_option("search", "baidu_qianfan_api_key"):
        key = cfg["search"]["baidu_qianfan_api_key"].strip()
        if key:
            search = SearchConfig(
                api_key=key,
                base_url=cfg.get("search", "base_url", fallback=DEFAULT_SEARCH_BASE_URL),
            )

    # ---- [mcp] 节 ----
    mcp = MCPConfig(
        connect_timeout=cfg.getfloat("mcp", "connect_timeout", fallback=DEFAULT_MCP_CONNECT_TIMEOUT),
        call_timeout=cfg.getfloat("mcp", "call_timeout", fallback=DEFAULT_MCP_CALL_TIMEOUT),
        disconnect_timeout=cfg.getfloat("mcp", "disconnect_timeout", fallback=DEFAULT_MCP_DISCONNECT_TIMEOUT),
        async_load=cfg.getboolean("mcp", "async_load", fallback=True),
    )

    # ---- [session] 节 ----
    session = SessionConfig(
        session_dir=cfg.get("session", "session_dir", fallback=DEFAULT_SESSION_DIR),
        auto_save=cfg.getboolean("session", "auto_save", fallback=DEFAULT_SESSION_AUTO_SAVE),
    )

    # ---- [ui] 节 ----
    ui = UIConfig(
        spinner_interval=cfg.getfloat("ui", "spinner_interval", fallback=DEFAULT_SPINNER_INTERVAL),
        sidebar_width=cfg.getint("ui", "sidebar_width", fallback=DEFAULT_SIDEBAR_WIDTH),
    )

    return Settings(
        llm=llm,
        workspace_root=str(Path(workspace_root).resolve()),
        system_prompt=system_prompt,
        search=search,
        mcp=mcp,
        session=session,
        agent=AgentConfig(system_prompt=system_prompt, compact_threshold=compact_threshold),
        ui=ui,
    )


# ============== 模板生成 ==============

CONFIG_TEMPLATE = """# =============================================================================
# aAgent 配置文件
# =============================================================================
# 修改此文件后需要重启 aAgent 才能生效
# 所有路径相对于 config.ini 所在目录
# =============================================================================

[llm]
# LLM API 地址（兼容 OpenAI 格式）
base_url = https://api.deepseek.com
# API Key（请替换为你的真实 Key）
api_key = sk-your-actual-api-key-here
# 模型名称
model = deepseek-flash
# 上下文窗口大小（Tokens），留空使用默认值 128000
; context_window = 128000
# 请求超时时间（秒）
; timeout = 60.0
# 采样温度（0.0-1.0，越高越随机）
; temperature = 0.7

[agent]
# 工作区根目录（Agent 允许访问的文件操作范围）
workspace_root = {workspace_root}
# System Prompt（可选，Agent 的行为基调）
system_prompt = 你是一个智能助手，可以帮助用户完成各种任务。
# 上下文压缩阈值（达到该比例后提示 /compact）
; compact_threshold = 0.8

[search]
# 百度千帆搜索 API Key（可选，配置后启用 searchWeb 工具）
baidu_qianfan_api_key = 
# 搜索 API 地址
; base_url = https://qianfan.baidubce.com/v2/ai_search

[mcp]
# MCP Server 连接超时（秒）
; connect_timeout = 30.0
# MCP 工具调用超时（秒）
; call_timeout = 30.0
# MCP 断开连接超时（秒）
; disconnect_timeout = 5.0
# 是否异步加载 MCP（先进入 TUI 界面，后台加载 MCP 工具）
; async_load = true

[session]
# 会话历史保存目录（相对于 workspace_root）
; session_dir = .agents/sessions
# 是否自动保存会话（每次新消息后保存）
; auto_save = true

[ui]
# Spinner 刷新间隔（秒）
; spinner_interval = 0.12
# 侧栏宽度（字符数）
; sidebar_width = 40
"""


def generate_template(config_path: Path) -> None:
    """生成一个带 mock 信息的 config.ini 模板文件。"""
    workspace_root = str(config_path.parent)
    content = CONFIG_TEMPLATE.format(workspace_root=workspace_root)
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(content)
