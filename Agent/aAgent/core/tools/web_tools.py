"""网络搜索工具：百度千帆 AI Search。"""
from typing import Optional
import json
import urllib.request
import urllib.error

from .registry import Tool, ToolRegistry


def register_search_tools(registry: ToolRegistry, api_key: Optional[str], base_url: str) -> None:
    """注册 searchWeb 工具；api_key 为空时仍注册，但调用时返回友好提示。"""

    def _do_search(query: str) -> str:
        if not api_key:
            return "搜索功能未配置：缺少 [search] 小节的 baidu_qianfan_api_key。"
        payload = json.dumps({
            "messages": [{"role": "user", "content": query}],
            "search_source": "baidu_search_v2",
        }).encode("utf-8")
        req = urllib.request.Request(
            base_url,
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return f"搜索 API 返回错误 HTTP {exc.code}: {detail[:500]}"
        except urllib.error.URLError as exc:
            return f"搜索 API 网络错误: {exc.reason}"
        except Exception as exc:
            return f"搜索请求失败: {type(exc).__name__}: {exc}"
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return f"搜索 API 返回了非 JSON 响应: {body[:300]}"

        # 百度千帆 AI 搜索可能返回 answer / result / content 中的任何一种
        parts = []
        answer = data.get("answer") or data.get("result") or data.get("content") or data.get("summary")
        if isinstance(answer, str) and answer.strip():
            parts.append(answer.strip())
        # 参考来源可能叫 references / search_result / results
        refs = (
            data.get("references")
            or data.get("search_result")
            or data.get("results")
            or data.get("web_results")
            or []
        )
        if isinstance(refs, list) and refs:
            lines = ["参考来源:"]
            for idx, item in enumerate(refs[:5], 1):
                if isinstance(item, dict):
                    title = (
                        item.get("title")
                        or item.get("name")
                        or item.get("displayName")
                        or "(无标题)"
                    )
                    url = (
                        item.get("url")
                        or item.get("link")
                        or item.get("displayUrl")
                        or ""
                    )
                    snippet = item.get("snippet") or item.get("description") or ""
                    line = f"  {idx}. {title}"
                    if url:
                        line += f" — {url}"
                    if snippet:
                        line += f"\n     {snippet[:120]}"
                    lines.append(line)
            parts.append("\n".join(lines))
        if not parts:
            parts.append("搜索 API 未返回可识别的 answer / references，原始响应摘要:")
            parts.append(json.dumps(data, ensure_ascii=False)[:1000])
        return "\n\n".join(parts)

    def handler(args: dict) -> str:
        return _do_search(args["query"])

    registry.add(Tool(
        "searchWeb",
        "使用百度千帆联网搜索，获取互联网上的最新信息。适合查询实时事件、新闻、天气预报、价格、官网文档等。",
        handler,
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词或完整问题"},
            },
            "required": ["query"],
        },
    ))
