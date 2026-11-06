"""Todo tool: the model keeps a visible task list in the session."""

import time
from typing import Any

from coderagent.core.events import Event, EventType
from coderagent.tools.base import ToolContext, ToolResult

STATUSES = ("pending", "in_progress", "completed")


class TodoWriteTool:
    name = "todo_write"
    description = (
        "Record the task list for the current work. Replaces the previous list. "
        "Each item has `content`, `status` (pending, in_progress or completed) and an optional `activeForm`."
    )
    parameters = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "The full task list.",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "status": {"type": "string", "enum": list(STATUSES)},
                        "activeForm": {"type": "string"},
                    },
                    "required": ["content", "status"],
                },
            },
        },
        "required": ["todos"],
    }

    def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        todos = params.get("todos")
        if not isinstance(todos, list):
            return ToolResult("Error: `todos` is required and must be an array.", is_error=True)
        for index, todo in enumerate(todos):
            if not isinstance(todo, dict):
                return ToolResult(f"Error: todo #{index + 1} must be an object.", is_error=True)
            if not isinstance(todo.get("content"), str) or not todo["content"].strip():
                return ToolResult(f"Error: todo #{index + 1} needs a non-empty `content`.", is_error=True)
            if todo.get("status") not in STATUSES:
                return ToolResult(
                    f"Error: todo #{index + 1} has invalid status '{todo.get('status')}'. Use one of {', '.join(STATUSES)}.",
                    is_error=True,
                )

        ctx.session.metadata["todos"] = todos
        ctx.bus.publish(
            Event(
                type=EventType.TOOL_RESULT,
                session_id=ctx.session.id,
                timestamp=time.time(),
                payload={"tool": self.name, "todos": todos},
            )
        )
        done = sum(1 for todo in todos if todo["status"] == "completed")
        return ToolResult(f"Task list updated ({done}/{len(todos)} completed).", metadata={"todos": todos})
