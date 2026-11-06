"""Skill 动态加载 / 创建工具：loadSkill + createSkill。"""
from typing import TYPE_CHECKING

from .registry import Tool, ToolRegistry

if TYPE_CHECKING:
    from ..skills import SkillManager


def register_skill_tools(registry: ToolRegistry, skills: "SkillManager") -> None:
    """注册 loadSkill + createSkill 工具，依赖 SkillManager 实例。"""

    # ---------- loadSkill ----------

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

    # ---------- createSkill ----------

    def create_skill(args: dict) -> str:
        return skills.create_skill(args["name"], args["skillContext"])

    registry.add(Tool(
        "createSkill",
        "根据用户需求创建新的 Skill。会在 .agents/skills/ 下自动创建合法目录名（小写+连字符）并写入 SKILL.md。"
        "SKILL.md 必须包含 YAML Frontmatter（name / description）和完整正文。"
        "目录创建成功后，如需 references/、scripts/ 等附加目录或辅助文件，请继续调用文件工具完成。",
        create_skill,
        {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill 的名称（自然语言即可，工具会自动转为合法目录名，如 'Code Review' → 'code-review'）",
                },
                "skillContext": {
                    "type": "string",
                    "description": (
                        "SKILL.md 的完整内容，必须以 YAML Frontmatter 开头，包含 name 和 description 两个字段，"
                        "格式为：\\n---\\nname: 显示名称\\ndescription: 一句话描述\\n---\\n\\n正文指令..."
                    ),
                },
            },
            "required": ["name", "skillContext"],
        },
    ))
