#!/usr/bin/env python3
"""AnythingLLM MCP Server (MVP): 获取第一个工作区的文件信息。
Streamable HTTP，兼容 MCP 新旧协议（SDK 自动按 MCP-Protocol-Version 路由）。"""
import os

import httpx
import uvicorn
from mcp.server.mcpserver import MCPServer

BASE = os.environ.get("ANYTHINGLLM_BASE", "http://localhost:3001/api/v1")
HEADERS = {"Authorization": f"Bearer {os.environ.get('ANYTHINGLLM_API_KEY', 'EQC554F-D1GM4WE-J78HA1G-BZ07N93')}"}

mcp = MCPServer("anythingllm")


@mcp.tool()
async def first_workspace_documents() -> dict:
    """获取 AnythingLLM 第一个工作区的名称及其中嵌入的文件信息。"""
    async with httpx.AsyncClient(timeout=30) as client:
        ws = (await client.get(f"{BASE}/workspaces", headers=HEADERS)).raise_for_status().json()
        first = ws["workspaces"][0]
        detail = (await client.get(f"{BASE}/workspace/{first['slug']}", headers=HEADERS)).raise_for_status().json()
        data = detail["workspace"][0]
        return {"workspace": data["name"], "slug": data["slug"], "documents": data.get("documents", [])}


app = mcp.streamable_http_app()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9001)
