"""网页抓取工具：curl 获取 HTML + trafilatura 提取正文。"""
import re
import subprocess
from typing import Optional, Tuple

from .registry import Tool, ToolRegistry


_CURL_TIMEOUT = 20           # 秒
_MAX_CONTENT_CHARS = 8000    # 正文过长时截断，避免撑爆上下文


def _decode_bytes(raw: bytes) -> str:
    """按常见编码依次尝试解码，保证中文页面不乱码。"""
    # 先从 HTML meta 里嗅探 charset
    sniff = raw[:2048].decode("ascii", errors="ignore")
    m = re.search(r'charset=["\']?([\w-]+)', sniff, re.IGNORECASE)
    candidates = []
    if m:
        candidates.append(m.group(1))
    candidates += ["utf-8", "gb2312", "gbk", "gb18030", "latin-1"]
    for enc in candidates:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def register_fetch_web_tools(registry: ToolRegistry) -> None:
    """注册 fetchWeb 工具；不依赖额外配置，始终可用。"""

    def _fetch_html(url: str) -> Tuple[str, int]:
        """用 curl 抓取网页源码，返回 (html, http_status)，失败时抛异常。"""
        try:
            result = subprocess.run(
                [
                    "curl.exe",
                    "-sS",            # 静默 + 显示错误
                    "-L",             # 跟随重定向
                    "-k",             # 忽略自签名/中间人证书（学校内网常见）
                    "--http1.1",      # 强制 HTTP/1.1，避免 HTTP/2 兼容问题
                    "--tlsv1.2",      # 强制 TLS 1.2，老旧服务器兼容
                    "--max-time", str(_CURL_TIMEOUT),
                    "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                    "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "-H", "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8",
                    "-H", "Accept-Encoding: identity",   # 不压缩，避免解压问题
                    "-H", f"Referer: {url}",
                    "-w", "\n%{http_code}",              # 末尾输出 HTTP 状态码
                    url,
                ],
                capture_output=True,
                timeout=_CURL_TIMEOUT + 5,
            )
        except FileNotFoundError:
            raise RuntimeError("未找到 curl.exe，请确认系统已安装 curl 并加入 PATH")
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"curl 执行超时（>{_CURL_TIMEOUT + 5} 秒）")

        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="replace").strip() or "(无错误输出)"
            raise RuntimeError(f"curl 失败 (exit {result.returncode}): {err[:300]}")

        raw = result.stdout or b""
        # 分离 HTTP 状态码（curl -w 在末尾追加的 \nNNN）
        http_status = 0
        if raw:
            # 从末尾找最后一个换行后的数字
            tail_match = re.search(rb"\n(\d{3})\s*$", raw)
            if tail_match:
                http_status = int(tail_match.group(1))
                raw = raw[:tail_match.start()]

        if not raw or not raw.strip():
            # stdout 空但 returncode 0：很可能是 TLS/WAF/网络问题，把 stderr 也带上
            err = result.stderr.decode("utf-8", errors="replace").strip()
            detail = f"；stderr: {err[:300]}" if err else ""
            raise RuntimeError(f"curl 未返回任何内容（可能是目标站点不可达、TLS 握手失败或被 WAF 拦截{detail}）")

        html = _decode_bytes(raw)
        return html, http_status

    def _extract_markdown(html: str) -> Optional[str]:
        """用 trafilatura 从 HTML 中提取正文并转为 Markdown。"""
        try:
            import trafilatura
        except ImportError:
            raise RuntimeError("缺少依赖 trafilatura，请执行 pip install trafilatura")

        text = trafilatura.extract(
            html,
            output_format="markdown",
            include_links=True,
            include_images=False,
            favor_precision=True,
            deduplicate=True,
        )
        if text and text.strip():
            return text.strip()
        # trafilatura 提取不到（常见于 JS 动态渲染的 SPA 空壳或 404 页），
        # 兜底：从原始 HTML 中抽 <title> 和 <meta description>
        title = ""
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if m:
            title = m.group(1).strip()
        desc = ""
        m2 = re.search(
            r'<meta\s+[^>]*name=["\']description["\'][^>]*content=["\']([^"\']+)["\']',
            html,
            re.IGNORECASE,
        )
        if not m2:
            m2 = re.search(
                r'<meta\s+[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']description["\']',
                html,
                re.IGNORECASE,
            )
        if m2:
            desc = m2.group(1).strip()
        if not title and not desc:
            return None
        parts = []
        if title:
            parts.append(f"# {title}")
        if desc:
            parts.append(f"\n页面描述: {desc}")
        parts.append(
            "\n\n⚠️ 未能提取到正文内容。可能原因："
            "页面是 JavaScript 动态渲染的单页应用（SPA）、页面需要登录、或该页面已被删除/不存在。"
            "建议改用 searchWeb 搜索该页面内容或查找缓存版本。"
        )
        return "\n".join(parts)

    def handler(args: dict) -> str:
        url = args["url"].strip()
        if not url:
            return "错误: url 不能为空"
        if not url.startswith(("http://", "https://")):
            return "错误: url 必须以 http:// 或 https:// 开头"

        try:
            html, http_status = _fetch_html(url)
        except Exception as exc:
            return f"获取网页失败: {exc}"

        # HTTP 错误码优先处理：404/410 等说明页面不存在，不必再提取
        if http_status in (404, 410):
            return (
                f"获取网页失败：目标页面不存在（HTTP {http_status}）。\n"
                f"URL: {url}\n"
                f"该页面可能已被删除、移动或 URL 有误。建议改用 searchWeb 搜索相关信息。"
            )
        if http_status and http_status >= 400:
            return (
                f"获取网页失败：服务器返回 HTTP {http_status} 错误。\n"
                f"URL: {url}\n"
                f"可能原因：页面需要登录权限、临时不可用或链接已失效。"
            )

        try:
            markdown = _extract_markdown(html)
        except Exception as exc:
            return f"正文提取失败: {exc}"

        if not markdown:
            return (
                f"无法从 {url} 中提取任何内容（页面可能为空壳、"
                f"需要登录或被风控）。建议改用 searchWeb 搜索相关信息。"
            )

        if len(markdown) > _MAX_CONTENT_CHARS:
            markdown = markdown[:_MAX_CONTENT_CHARS] + f"\n\n…（内容过长，已截断至 {_MAX_CONTENT_CHARS} 字）"

        status_note = f"（HTTP {http_status}）" if http_status else ""
        return f"来源: {url} {status_note}\n\n{markdown}"

    registry.add(Tool(
        "fetchWeb",
        "获取指定网页的主要内容（自动去除导航、广告、页脚，保留标题、段落、列表、表格与链接），返回 Markdown 格式。适合在 searchWeb 给出参考来源后深入阅读全文。",
        handler,
        {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "完整的网页 URL，如 https://docs.python.org/3/whatsnew/3.13.html"},
            },
            "required": ["url"],
        },
    ))
