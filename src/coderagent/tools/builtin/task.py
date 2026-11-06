"""The `task` tool: hand a self contained job to a sub agent."""

from typing import Any

from coderagent.core.subagent import SubagentSpec, render_result
from coderagent.tools.base import ToolContext, ToolResult


class TaskTool:
    """Delegate a task to a sub agent that works in its own context."""

    name = "task"
    description = (
        "Delegate a self contained job to a sub agent. The sub agent works in its own context, "
        "so its intermediate output does not fill up yours. Give it everything it needs: it "
        "cannot see this conversation. Good for: searching the whole code base, doing a broad "
        "refactor, checking a result independently."
    )
    parameters = {
        "type": "object",
        "properties": {
            "subagent_type": {"type": "string", "description": "The name of the sub agent."},
            "description": {"type": "string", "description": "What the job is, in one sentence."},
            "prompt": {"type": "string", "description": "The full instructions for the sub agent."},
        },
        "required": ["subagent_type", "description", "prompt"],
    }

    def __init__(self, runner=None, specs: dict[str, SubagentSpec] | None = None) -> None:
        self.runner = runner
        """The thing that runs the sub agent. Set by the assembly of the agent."""
        self.specs = specs or {}
        """The sub agents that are available, by name."""

    def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        name = str(params.get("subagent_type", ""))
        spec = self.specs.get(name)
        if spec is None:
            return ToolResult(
                f"Error: unknown sub agent '{name}'. Available sub agents: {', '.join(sorted(self.specs)) or 'none'}.",
                is_error=True,
            )
        if self.runner is None:
            return ToolResult("Error: the sub agents are not available in this session.", is_error=True)
        description = str(params.get("description", ""))
        prompt = str(params.get("prompt", ""))
        result = self.runner.run(spec, description, prompt)
        return ToolResult(render_result(result), is_error=result["status"] == "error")


__all__ = ["TaskTool"]
