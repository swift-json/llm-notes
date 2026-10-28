"""Skill 动态加载工具：loadSkill。"""
from typing import TYPE_CHECKING

from .registry import Tool, ToolRegistry

if TYPE_CHECKING:
    from ..skills import SkillManager


def register_skill_tools(registry: ToolRegistry, skills: "SkillManager") -> None:
    """注册 loadSkill 工具，依赖 SkillManager 实例。"""

    def load_skill(args: dict) -> str:
        name = args["name"]
        filename = args.get("filename")

        if filename:
            return skills.load_file(name, filename)

        content = skills.load_skill_md(name)
        if content is None:
            available = ", ".join(f"`{s.name}`" for s in skills.skills) or "(无)"
            return f"错误: 未找到 Skill `{name}`。当前可用: {available}"
        return content

    registry.add(Tool(
        "loadSkill",
        "加载某个 Skill 的完整指令或附加文件。首次调用只传 name 即可获取该 Skill 的 SKILL.md 全文；"
        "若需要 Skill 引用的其他文件，再附加 filename 参数。",
        load_skill,
        {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill 的名称（与 SKILL.md Frontmatter 中的 name 一致）"},
                "filename": {
                    "type": "string",
                    "description": "可选，需要读取的附加文件名或相对路径。留空则读取该 Skill 的 SKILL.md 全文",
                },
            },
            "required": ["name"],
        },
    ))
