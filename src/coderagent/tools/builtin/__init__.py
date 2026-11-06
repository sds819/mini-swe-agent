"""The built-in tool set."""

from coderagent.tools.base import Tool
from coderagent.tools.builtin.fs import EditTool, MultiEditTool, ReadTool, WriteTool
from coderagent.tools.builtin.search import GlobTool, GrepTool, LsTool
from coderagent.tools.builtin.shell import BashKillTool, BashOutputTool, BashTool
from coderagent.tools.builtin.todo import TodoWriteTool
from coderagent.tools.registry import ToolRegistry

ALL_TOOLS: list[Tool] = [
    ReadTool(),
    WriteTool(),
    EditTool(),
    MultiEditTool(),
    GlobTool(),
    GrepTool(),
    LsTool(),
    BashTool(),
    BashOutputTool(),
    BashKillTool(),
    TodoWriteTool(),
]

TOOL_NAMES = [tool.name for tool in ALL_TOOLS]


def build_registry(enabled: list[str] | None = None, disabled: list[str] | None = None) -> ToolRegistry:
    """Registry with the built-in tools, minus the disabled ones."""
    allowed = set(enabled) if enabled else set(TOOL_NAMES)
    return ToolRegistry([tool for tool in ALL_TOOLS if tool.name in allowed and tool.name not in set(disabled or [])])


__all__ = ["ALL_TOOLS", "TOOL_NAMES", "build_registry"]
