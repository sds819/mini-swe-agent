"""The `skill` tool: the instructions of a skill, when the model needs them."""

from typing import Any

from coderagent.extensions.skills import Skill
from coderagent.tools.base import ToolContext, ToolResult


class SkillTool:
    """Load a skill: its instructions, and where its files are."""

    name = "skill"
    description = (
        "Load the instructions of a skill. A skill is a package of steps, scripts and templates "
        "for a kind of task. Call this when the description of a skill fits what the user asked for, "
        "then follow the instructions it gives."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The name of the skill."},
        },
        "required": ["name"],
    }

    def __init__(self, skills: dict[str, Skill] | None = None) -> None:
        self.skills = skills or {}

    def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        name = str(params.get("name", ""))
        skill = self.skills.get(name)
        if skill is None:
            return ToolResult(
                f"Error: unknown skill '{name}'. Available skills: {', '.join(sorted(self.skills)) or 'none'}.",
                is_error=True,
            )
        where = f"\n\nThe files of the skill are in {skill.directory}." if skill.directory else ""
        return ToolResult(skill.render() + where)


__all__ = ["SkillTool"]
