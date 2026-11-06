"""MCP 客户端适配器：连接外部 MCP Server，发现并调用其工具。

支持 stdio 和 streamable_http 两种传输协议。
工具命名规则：{server_name}_{tool_name}，避免不同服务器之间的名称冲突。

核心架构：每个 MCP Server 连接在独立的后台线程中运行 asyncio 事件循环，
保持连接持续存活。所有 MCP 操作（list_tools、call_tool、disconnect）通过
asyncio.run_coroutine_threadsafe() 投递到对应的事件循环中执行。
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# MCP Python SDK 是可选依赖。缺少时模块仍可导入（MCP_AVAILABLE=False），
# register_mcp_tools() 会打印提示并返回 None，其他本地工具不受影响。
try:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.client.streamable_http import streamable_http_client
    from mcp.types import CallToolResult, TextContent, Tool
    MCP_AVAILABLE = True
except ModuleNotFoundError:
    MCP_AVAILABLE = False
    ClientSession = None  # type: ignore[assignment,misc]
    CallToolResult = None  # type: ignore[assignment,misc]
    TextContent = None  # type: ignore[assignment,misc]
    Tool = None  # type: ignore[assignment,misc]
    StdioServerParameters = None  # type: ignore[assignment,misc]
    stdio_client = None  # type: ignore[assignment,misc]
    streamable_http_client = None  # type: ignore[assignment,misc]

# 兼容两种导入方式：作为包子模块时用相对导入，独立运行时用绝对导入
try:
    from .registry import Tool as AgentTool
    from .registry import ToolRegistry
except ImportError:
    from registry import Tool as AgentTool
    from registry import ToolRegistry

logger = logging.getLogger(__name__)

# 工具名前缀分隔符
PREFIX_SEP = "_"


@dataclass
class MCPServerConfig:
    """单个 MCP Server 的配置。"""

    name: str
    type: str  # "stdio" 或 "streamable_http"（也兼容 "http"）
    url: Optional[str] = None  # streamable_http 必需
    command: Optional[str] = None  # stdio 必需
    args: List[str] = field(default_factory=list)  # stdio 可选
    env: Optional[Dict[str, str]] = None  # stdio 可选
    cwd: Optional[str] = None  # stdio 可选


class MCPServerConnection:
    """维护与单个 MCP Server 的连接。

    在后台线程中运行 asyncio 事件循环，保持 MCP 连接持续存活。
    """

    def __init__(
        self,
        config: MCPServerConfig,
        connect_timeout: float = 30.0,
        call_timeout: float = 30.0,
        disconnect_timeout: float = 5.0,
    ) -> None:
        self.config = config
        self._connect_timeout = connect_timeout
        self._call_timeout = call_timeout
        self._disconnect_timeout = disconnect_timeout
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._connected = False
        self._stop_event: Optional[asyncio.Event] = None
        # 用于保持传输层和 session 存活的引用
        self._session: Optional[ClientSession] = None
        self._transport_aexit: Optional[Callable] = None  # 传输层的 __aexit__
        self._session_aexit: Optional[Callable] = None  # session 的 __aexit__

    @property
    def connected(self) -> bool:
        return self._connected and self._loop is not None and not self._loop.is_closed()

    def connect(self) -> None:
        """启动后台线程并建立连接。"""
        cfg = self.config
        transport_type = cfg.type.lower()

        # 验证配置
        if transport_type in ("streamable_http", "http"):
            if not cfg.url:
                raise ValueError(f"[{cfg.name}] streamable_http 类型需要 url 配置")
        elif transport_type == "stdio":
            if not cfg.command:
                raise ValueError(f"[{cfg.name}] stdio 类型需要 command 配置")
        else:
            raise ValueError(f"[{cfg.name}] 不支持的传输类型: {cfg.type}")

        # 创建事件循环并在线程中运行
        loop = asyncio.new_event_loop()
        self._loop = loop

        def thread_main():
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._connect_and_run(loop))

        self._thread = threading.Thread(
            target=thread_main,
            name=f"mcp-{cfg.name}",
            daemon=True,
        )
        self._thread.start()

        # 等待连接建立（带超时）
        self._wait_connected(timeout=self._connect_timeout)
        logger.info("MCP Server [%s] 连接成功", cfg.name)

    async def _connect_and_run(self, loop: asyncio.AbstractEventLoop) -> None:
        """在后台线程的事件循环中建立连接并保持运行。"""
        cfg = self.config
        self._stop_event = asyncio.Event()

        transport_type = cfg.type.lower()
        try:
            if transport_type in ("streamable_http", "http"):
                async with streamable_http_client(cfg.url) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        self._session = session
                        self._connected = True
                        # 等待停止信号
                        await self._stop_event.wait()
            elif transport_type == "stdio":
                server_params = StdioServerParameters(
                    command=cfg.command,
                    args=cfg.args,
                    env=cfg.env,
                    cwd=cfg.cwd,
                )
                async with stdio_client(server_params) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        self._session = session
                        self._connected = True
                        await self._stop_event.wait()
        except Exception:
            self._connected = False
            self._session = None
            raise

    def _wait_connected(self, timeout: float = 30.0) -> None:
        """等待连接建立，带超时。"""
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._connected:
                return
            if self._thread and not self._thread.is_alive():
                raise RuntimeError(f"[{self.config.name}] 连接线程已退出")
            time.sleep(0.05)
        raise TimeoutError(f"[{self.config.name}] 连接超时 ({timeout}s)")

    def disconnect(self) -> None:
        """断开连接，停止后台线程。"""
        if not self._connected and not self._loop:
            return

        try:
            if self._loop and not self._loop.is_closed():
                # 投递停止信号
                future = asyncio.run_coroutine_threadsafe(
                    self._signal_stop(),
                    self._loop,
                )
                try:
                    future.result(timeout=self._disconnect_timeout)
                except Exception as exc:
                    logger.warning("等待停止信号时出错: %s", exc)

                # 等待线程结束
            if self._thread:
                self._thread.join(timeout=self._disconnect_timeout)
        except Exception as exc:
            logger.warning("断开 [%s] 时出错: %s", self.config.name, exc)
        finally:
            self._connected = False
            self._session = None
            self._loop = None
            self._thread = None

    async def _signal_stop(self) -> None:
        """发送停止信号。"""
        if self._stop_event:
            self._stop_event.set()

    def _run_async(self, coro):
        """将协程投递到后台事件循环执行并返回结果。"""
        if not self._loop or not self._connected:
            raise RuntimeError(f"[{self.config.name}] 未连接")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=self._call_timeout)

    def list_tools(self) -> List[Tool]:
        """获取工具列表（同步接口）。"""
        return self._run_async(self._list_tools_async())

    async def _list_tools_async(self) -> List[Tool]:
        result = await self._session.list_tools()
        return result.tools

    def call_tool(self, tool_name: str, arguments: dict) -> CallToolResult:
        """调用工具（同步接口）。"""
        return self._run_async(self._call_tool_async(tool_name, arguments))

    async def _call_tool_async(self, tool_name: str, arguments: dict) -> CallToolResult:
        return await self._session.call_tool(tool_name, arguments)

    @staticmethod
    def _format_exception(exc: BaseException) -> str:
        """展开 ExceptionGroup 为可读字符串。"""
        if isinstance(exc, BaseExceptionGroup):
            parts = []
            for sub in exc.exceptions:
                parts.append(sub.__class__.__name__)
                if str(sub):
                    parts[-1] += f": {sub}"
                if isinstance(sub, BaseExceptionGroup):
                    parts[-1] += f" [{MCPServerConnection._format_exception(sub)}]"
            return f"{exc.__class__.__name__}: {', '.join(parts)}"
        return f"{exc.__class__.__name__}: {exc}"


class MCPClientAdapter:
    """MCP 客户端适配器：管理多个 MCP Server 的连接和工具注册。"""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        connect_timeout: float = 30.0,
        call_timeout: float = 30.0,
        disconnect_timeout: float = 5.0,
    ) -> None:
        self._connections: Dict[str, MCPServerConnection] = {}
        self._server_tools: Dict[str, List[str]] = {}  # server_name -> [prefixed_tool_names]
        self._tool_to_server: Dict[str, str] = {}  # prefixed_tool_name -> server_name
        self._config_path = config_path
        self._connect_timeout = connect_timeout
        self._call_timeout = call_timeout
        self._disconnect_timeout = disconnect_timeout
        # 异步加载回调：MCP 工具发现完成后通知上层
        self._on_loaded: Optional[Callable[[], None]] = None

    def set_on_loaded(self, callback: Callable[[], None]) -> None:
        """设置 MCP 加载完成后的回调（用于动态刷新 TUI）。"""
        self._on_loaded = callback

    @property
    def server_info(self) -> List[dict]:
        """返回当前已连接的 MCP 服务器及其工具信息列表。"""
        result = []
        for name, conn in self._connections.items():
            tools = self._server_tools.get(name, [])
            tool_details = []
            for t in tools:
                for agent_tool in conn._run_async(conn._list_tools_async()):
                    if f"{name}{PREFIX_SEP}{agent_tool.name}" == t:
                        tool_details.append({
                            "name": t,
                            "description": agent_tool.description or agent_tool.name,
                        })
                        break
            result.append({
                "name": name,
                "connected": conn.connected,
                "tool_count": len(tools),
                "tools": tool_details,
            })
        return result

    def load_config(self, config_path: Path) -> List[MCPServerConfig]:
        """从 .mcp.json 加载 MCP Server 配置。"""
        if not config_path.exists():
            logger.info("MCP 配置文件不存在: %s", config_path)
            return []

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("读取 MCP 配置失败: %s", exc)
            return []

        servers = raw.get("mcpServers", {})
        configs: List[MCPServerConfig] = []
        for name, entry in servers.items():
            try:
                config = MCPServerConfig(
                    name=name,
                    type=entry.get("type", "streamable_http"),
                    url=entry.get("url"),
                    command=entry.get("command"),
                    args=entry.get("args", []),
                    env=entry.get("env"),
                    cwd=entry.get("cwd"),
                )
                configs.append(config)
            except Exception as exc:
                logger.error("解析 MCP Server [%s] 配置失败: %s", name, exc)
        return configs

    def connect_all(self, configs: List[MCPServerConfig]) -> None:
        """连接所有 MCP Server。连接失败不抛出，仅记录错误。"""
        for cfg in configs:
            try:
                conn = MCPServerConnection(
                    cfg,
                    connect_timeout=self._connect_timeout,
                    call_timeout=self._call_timeout,
                    disconnect_timeout=self._disconnect_timeout,
                )
                conn.connect()
                self._connections[cfg.name] = conn
            except Exception as exc:
                msg = MCPServerConnection._format_exception(exc)
                print(f"[MCP] Server [{cfg.name}] 连接失败: {msg}", file=sys.stderr)
                logger.error("MCP Server [%s] 连接失败: %s", cfg.name, msg)

    def disconnect_all(self) -> None:
        """断开所有连接。"""
        for name, conn in list(self._connections.items()):
            try:
                conn.disconnect()
            except Exception as exc:
                logger.warning("断开 [%s] 出错: %s", name, exc)
        self._connections.clear()
        self._server_tools.clear()
        self._tool_to_server.clear()

    def discover_and_register(self, registry: ToolRegistry) -> None:
        """发现所有已连接服务器的工具，注册到 ToolRegistry。"""
        for server_name, conn in self._connections.items():
            try:
                tools = conn.list_tools()
                registered = []
                for tool in tools:
                    prefixed_name = f"{server_name}{PREFIX_SEP}{tool.name}"
                    # 避免重复注册
                    if prefixed_name in self._tool_to_server:
                        continue
                    # 避免与本地工具冲突
                    if prefixed_name in [t.name for t in registry._tools.values()]:
                        logger.warning("工具名冲突，跳过: %s", prefixed_name)
                        continue

                    agent_tool = AgentTool(
                        name=prefixed_name,
                        description=f"[MCP/{server_name}] {tool.description or tool.name}",
                        handler=self._make_tool_handler(server_name, tool.name, prefixed_name),
                        parameters=tool.input_schema or {"type": "object", "properties": {}},
                    )
                    registry.add(agent_tool)
                    self._tool_to_server[prefixed_name] = server_name
                    registered.append(prefixed_name)

                self._server_tools[server_name] = registered
                if registered:
                    logger.info("MCP Server [%s] 注册了 %d 个工具: %s",
                                server_name, len(registered), registered)
                    print(f"[MCP] Server [{server_name}] 注册了 {len(registered)} 个工具: {', '.join(registered)}")
            except Exception as exc:
                msg = MCPServerConnection._format_exception(exc)
                logger.error("发现 [%s] 工具失败: %s", server_name, msg)
                print(f"[MCP] Server [{server_name}] 发现工具失败: {msg}", file=sys.stderr)

    def _make_tool_handler(
        self, server_name: str, original_name: str, prefixed_name: str
    ) -> Callable[[dict], str]:
        """创建工具调用处理器。"""

        def handler(args: dict) -> str:
            conn = self._connections.get(server_name)
            if not conn or not conn.connected:
                return f"[MCP] Server [{server_name}] 未连接，无法调用工具 {original_name}"
            try:
                result = conn.call_tool(original_name, args)
                return self._format_tool_result(result)
            except Exception as exc:
                msg = MCPServerConnection._format_exception(exc)
                return f"[MCP] 调用 {prefixed_name} 失败: {msg}"

        handler.__name__ = f"mcp_{server_name}_{original_name}"
        return handler

    @staticmethod
    def _format_tool_result(result: CallToolResult) -> str:
        """将 CallToolResult 格式化为字符串返回给 LLM。"""
        if result.is_error:
            parts = ["[MCP] 工具执行出错:"]
            for block in result.content:
                if isinstance(block, TextContent):
                    parts.append(block.text)
                else:
                    parts.append(str(block))
            return "\n".join(parts)

        parts: List[str] = []
        for block in result.content:
            if isinstance(block, TextContent):
                parts.append(block.text)
            else:
                # ImageContent / AudioContent / BlobContent 等
                parts.append(f"[{block.type}] (非文本内容)")

        return "\n".join(parts) if parts else "(工具无返回内容)"


def register_mcp_tools(
    registry: ToolRegistry,
    config_path: Optional[Path] = None,
    connect_timeout: float = 30.0,
    call_timeout: float = 30.0,
    disconnect_timeout: float = 5.0,
    async_load: bool = False,
    on_loaded: Optional[Callable[[], None]] = None,
) -> Optional[MCPClientAdapter]:
    """便捷函数：加载 MCP 配置、连接服务器、注册工具。

    返回 MCPClientAdapter 实例（调用方可在退出时调用 disconnect_all()），
    若没有配置、MCP SDK 未安装或全部连接失败则返回 None。

    async_load=True 时：立即返回 adapter（可能尚未加载完成），在后台线程异步连接和注册工具。
    on_loaded 回调会在异步加载完成后被调用（供 UI 层刷新）。
    """
    if not MCP_AVAILABLE:
        # 仅在存在 MCP 配置文件时才提示，避免每次启动都刷屏
        check_path = config_path or (Path.cwd() / ".mcp.json")
        if check_path.exists():
            print(
                "[MCP] 警告: 未检测到 mcp Python SDK（需要 Python ≥ 3.10），"
                "跳过 MCP 工具加载。安装命令: pip install mcp",
                file=sys.stderr,
            )
        return None

    # 优先使用传入路径，否则用当前工作目录的 .mcp.json
    if config_path is None:
        config_path = Path.cwd() / ".mcp.json"

    adapter = MCPClientAdapter(
        config_path,
        connect_timeout=connect_timeout,
        call_timeout=call_timeout,
        disconnect_timeout=disconnect_timeout,
    )
    configs = adapter.load_config(config_path)

    if not configs:
        logger.info("未配置任何 MCP Server")
        return None

    adapter.set_on_loaded(on_loaded)

    if async_load:
        # 异步加载：后台线程连接并注册工具，不阻塞主线程
        def async_worker():
            try:
                adapter.connect_all(configs)
                adapter.discover_and_register(registry)
                if on_loaded:
                    try:
                        on_loaded()
                    except Exception as exc:
                        logger.error("MCP 加载回调执行失败: %s", exc)
            except Exception as exc:
                msg = MCPServerConnection._format_exception(exc)
                logger.error("MCP 异步加载失败: %s", msg)
                if on_loaded:
                    try:
                        on_loaded()  # 即使失败也通知 UI 结束 loading
                    except Exception:
                        pass

        threading.Thread(target=async_worker, name="mcp-async-loader", daemon=True).start()
        return adapter  # 提前返回，此时可能尚未注册任何 MCP 工具

    # 同步加载：阻塞直到完成
    adapter.connect_all(configs)
    adapter.discover_and_register(registry)
    if on_loaded:
        on_loaded()

    return adapter if adapter._connections else None
