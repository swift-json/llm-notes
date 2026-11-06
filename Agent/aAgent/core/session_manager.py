"""会话管理：持久化、恢复、AGENTS.md 注入。

设计策略：
- 会话文件保存为 JSON 格式，包含消息历史、元数据、AGENTS.md 内容标记
- AGENTS.md 采用"一次注入，全程复用"策略：首次加载时读取并作为 system 消息注入，
  并持久化到会话事件日志里，后续轮次直接复用
"""
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .context_manager import to_record


# 会话文件元数据标记
AGENTS_MD_MARKER = "__agents_md_loaded__"


class SessionManager:
    """管理会话的保存、恢复和历史列表。"""

    def __init__(self, session_dir: Path, workspace_root: str) -> None:
        self._session_dir = Path(session_dir)
        self._workspace_root = workspace_root
        self._session_dir.mkdir(parents=True, exist_ok=True)

    @property
    def session_dir(self) -> Path:
        return self._session_dir

    # ---------- 保存 ----------

    def save_session(
        self,
        session_id: str,
        messages: List[dict],
        turns: int,
        agents_md_loaded: bool = False,
    ) -> Path:
        """保存当前会话到文件，返回文件路径。"""
        path = self._session_dir / f"{session_id}.json"
        data = {
            "session_id": session_id,
            "saved_at": datetime.now().isoformat(),
            "turns": turns,
            "agents_md_loaded": agents_md_loaded,
            "messages": [to_record(m) for m in messages],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path

    # ---------- 恢复 ----------

    def load_session(self, session_id: str) -> Optional[dict]:
        """加载指定会话，返回会话数据字典（含 messages 列表）。"""
        path = self._session_dir / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    # ---------- 列表 ----------

    def list_sessions(self) -> List[dict]:
        """获取所有历史会话列表，按保存时间倒序。"""
        sessions: List[dict] = []
        for path in sorted(self._session_dir.glob("*.json"), reverse=True):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                sessions.append({
                    "session_id": data.get("session_id", path.stem),
                    "saved_at": data.get("saved_at", ""),
                    "turns": data.get("turns", 0),
                    "message_count": len(data.get("messages", [])),
                    "agents_md_loaded": data.get("agents_md_loaded", False),
                    "first_user_msg": self._extract_first_user(data.get("messages", [])),
                    "path": str(path),
                })
            except (json.JSONDecodeError, OSError):
                continue
        return sessions

    @staticmethod
    def _extract_first_user(messages: List[dict]) -> str:
        """从消息列表中提取第一条用户消息的摘要，用于会话列表展示。"""
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "") or ""
                return content[:60] + ("..." if len(content) > 60 else "")
        return "(空会话)"

    def delete_session(self, session_id: str) -> bool:
        """删除指定会话文件。"""
        path = self._session_dir / f"{session_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    # ---------- AGENTS.md ----------

    def load_agents_md(self, project_root: Path) -> Optional[str]:
        """读取项目根目录的 AGENTS.md 文件。

        采用"一次注入，全程复用"策略：
        - 首次调用时读取内容并返回
        - 后续通过会话持久化直接复用已注入的消息

        返回文件内容（去除首尾空白），不存在或读取失败返回 None。
        """
        agents_md_path = Path(project_root) / "AGENTS.md"
        if not agents_md_path.is_file():
            return None
        try:
            with open(agents_md_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            return content if content else None
        except OSError:
            return None

    @staticmethod
    def make_agents_md_message(content: str) -> dict:
        """将 AGENTS.md 内容封装为一条 system 消息。"""
        return {
            "role": "system",
            "content": (
                "以下是项目根目录的 AGENTS.md 文件内容，定义了该项目的开发规范、约束和约定。\n"
                "你必须在整个会话中持续遵守这些规则：\n\n"
                "--- AGENTS.md ---\n"
                f"{content}\n"
                "--- end AGENTS.md ---"
            ),
        }
