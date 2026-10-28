"""命令行工具：调用本地已安装的任意 CLI 程序。"""
import subprocess

from .registry import Tool, ToolRegistry

TIMEOUT = 30        # 执行超时（秒）
MAX_OUTPUT = 4000   # stdout / stderr 单段最大字符数


def _decode(raw: bytes) -> str:
    """CLI 输出编码不统一，按 utf-8 → gbk 顺序尝试。"""
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _truncate(text: str, label: str) -> str:
    """超长输出保留首尾，中间标注截断信息。"""
    if len(text) <= MAX_OUTPUT:
        return text
    keep = MAX_OUTPUT // 2
    omitted = len(text) - keep * 2
    return f"{text[:keep]}\n... [{label} 已截断，中间省略 {omitted} 字符] ...\n{text[-keep:]}"


def register_cli_tools(registry: ToolRegistry) -> None:
    def run_cli(args: dict) -> str:
        command = args["command"]
        argv = [command] + [str(arg) for arg in args.get("args") or []]

        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                shell=False,        # 不拼接 Shell 字符串，避免注入
                timeout=TIMEOUT,
            )
        except FileNotFoundError:
            return f"错误: 未找到命令 {command}，请确认该 CLI 已安装并加入 PATH"
        except PermissionError:
            return f"错误: 没有权限执行 {command}"
        except subprocess.TimeoutExpired:
            return f"错误: 命令执行超时（超过 {TIMEOUT} 秒），已终止: {' '.join(argv)}"

        stdout = _truncate(_decode(result.stdout).strip(), "标准输出")
        stderr = _truncate(_decode(result.stderr).strip(), "标准错误")
        return (
            f"退出码: {result.returncode}\n"
            f"标准输出:\n{stdout or '(空)'}\n"
            f"标准错误:\n{stderr or '(空)'}"
        )

    registry.add(Tool(
        "RunCli",
        "执行本地已安装的命令行程序（CLI）。返回标准输出、标准错误和退出码，"
        "可根据退出码判断是否成功并决定下一步操作。适合 git、python、pip、dir 等命令。",
        run_cli,
        {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "程序名称，如 git、python、pip、curl"},
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "参数列表，每个参数作为独立字符串，如 [\"--version\"]、[\"status\", \"--short\"]",
                },
            },
            "required": ["command"],
        },
    ))
