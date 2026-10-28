"""Skill 发现与动态加载管理器。

约定：
- Skill 根目录：<project_root>/.agents/skills/
- 每个 Skill 一个子目录，内含 SKILL.md（YAML Frontmatter 定义 name / description）
- 初始化仅扫描 SKILL.md 头部元信息，正文按需通过 loadSkill 工具读取
"""
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Union

_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---",
    re.DOTALL,
)


@dataclass
class SkillMeta:
    """Skill 元信息（仅 name / description，不包含正文）。"""
    name: str
    description: str
    dir: Path          # Skill 子目录绝对路径
    skill_md: Path     # SKILL.md 绝对路径


class SkillManager:
    """扫描 .agents/skills/ 并管理按需加载。"""

    def __init__(self, project_root: Union[str, Path]) -> None:
        self._root = Path(project_root).resolve()
        self._skills: Dict[str, SkillMeta] = {}
        self.discover()

    @property
    def skills_dir(self) -> Path:
        return self._root / ".agents" / "skills"

    @property
    def skills(self) -> List[SkillMeta]:
        return list(self._skills.values())

    # ---------- 发现 ----------

    def discover(self) -> None:
        """扫描 .agents/skills/ 下的所有 Skill 子目录。"""
        self._skills.clear()
        skills_dir = self.skills_dir
        if not skills_dir.is_dir():
            return
        for child in sorted(skills_dir.iterdir()):
            if not child.is_dir():
                continue
            skill_md = child / "SKILL.md"
            if not skill_md.is_file():
                continue
            meta = self._parse_meta(skill_md)
            if meta is not None:
                self._skills[meta.name] = meta

    @staticmethod
    def _parse_meta(skill_md: Path) -> Optional[SkillMeta]:
        """读取 SKILL.md 头部 YAML Frontmatter，提取 name / description。"""
        try:
            with open(skill_md, encoding="utf-8") as f:
                head = f.read(4096)   # 只读开头即可
        except OSError:
            return None

        # 容错：允许分隔线被手写成转义形式 "\---"，并忽略 BOM / 首尾空白
        normalized = "\n".join(
            "---" if line.strip().lstrip("\\").strip() == "---" else line
            for line in head.lstrip("\ufeff").splitlines()
        )
        m = _FRONTMATTER_RE.match(normalized)
        if not m:
            return None
        fm = m.group(1)
        data: Dict[str, str] = {}
        for line in fm.splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                data[key.strip().lstrip("\\").strip()] = val.strip().strip('"').strip("'")
        name = data.get("name")
        desc = data.get("description")
        if not name or not desc:
            return None
        return SkillMeta(name=name, description=desc, dir=skill_md.parent, skill_md=skill_md)

    # ---------- System Prompt 注入 ----------

    def prompt_snippet(self) -> str:
        """生成注入 System Prompt 的 Skill 列表段落。"""
        if not self._skills:
            return ""
        lines = ["You have access to the following skills:"]
        for meta in self._skills.values():
            lines.append(f"- `{meta.name}`: {meta.description}")
        lines.append(
            "Use the `loadSkill` tool to load the full instructions of a skill when needed. "
            "You can also load additional files referenced by a skill."
        )
        lines.append(
            "IMPORTANT: Before answering a user request, always check whether any skill above "
            "matches the task. If one matches, you MUST call `loadSkill` with that skill's name "
            "FIRST, then follow its instructions strictly. Do not skip this step even if you "
            "think you already know how to do the task."
        )
        return "\n".join(lines)

    # ---------- 按需加载 ----------

    def load_skill_md(self, name: str) -> Optional[str]:
        """读取指定 Skill 的 SKILL.md 全文。"""
        meta = self._skills.get(name)
        if meta is None:
            return None
        try:
            with open(meta.skill_md, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    def load_file(self, name: str, filename: str) -> str:
        """读取指定 Skill 子目录内的附加文件。

        - 优先精确路径匹配（相对于 Skill 目录）
        - 若只给文件名，递归搜索该 Skill 目录
        - 多个同名文件时返回候选路径
        - 路径越界 / 文件不存在均返回可读错误信息
        """
        meta = self._skills.get(name)
        if meta is None:
            return f"错误: 未找到 Skill `{name}`"

        skill_dir = meta.dir
        target = Path(filename)

        # 1) 精确路径匹配：相对于 Skill 目录
        exact = (skill_dir / filename).resolve()
        try:
            exact.relative_to(skill_dir)   # 防止 ../ 越界
        except ValueError:
            return f"错误: 路径 `{filename}` 试图访问 Skill 目录之外的文件"
        if exact.is_file():
            return self._read_text(exact)

        # 2) 绝对路径兼容
        if target.is_absolute():
            try:
                target.resolve().relative_to(skill_dir)
            except ValueError:
                return f"错误: 绝对路径 `{filename}` 不在 Skill `{name}` 目录内"
            if target.is_file():
                return self._read_text(target)

        # 3) 仅文件名：递归搜索该 Skill 目录
        matches: List[Path] = []
        for root, _dirs, files in os.walk(skill_dir):
            for fn in files:
                if fn == filename:
                    matches.append(Path(root) / fn)
        if len(matches) == 1:
            return self._read_text(matches[0])
        if len(matches) > 1:
            candidates = "\n".join(f"  - {p.relative_to(skill_dir)}" for p in matches)
            return (
                f"文件名 `{filename}` 在 Skill `{name}` 中存在多个匹配，"
                f"请指定相对路径：\n{candidates}"
            )
        return f"错误: 在 Skill `{name}` 目录下未找到 `{filename}`"

    @staticmethod
    def _read_text(path: Path) -> str:
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except OSError as exc:
            return f"错误: 无法读取 {path}: {exc}"
        if not content.strip():
            return f"(文件为空: {path.name})"
        return content
