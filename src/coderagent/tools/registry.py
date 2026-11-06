"""Tool registry: registration, schema generation and budget-aware trimming."""

import json
import logging

from coderagent.tools.base import Tool

logger = logging.getLogger("coderagent.tools")

# Trim order: the first tool in this list is dropped first.
TRIM_ORDER = [
    "web_search",
    "web_fetch",
    "todo_write",
    "bash_output",
    "bash_kill",
    "multi_edit",
    "write",
    "edit",
    "ls",
    "glob",
    "grep",
    "read",
    "bash",
]
NEVER_TRIM = {"bash", "read"}
CHARS_PER_TOKEN = 3.5


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            logger.warning("Tool '%s' is already registered, overwriting it", tool.name)
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self, budget_tokens: int | None = None) -> list[dict]:
        """OpenAI-compatible tool schemas, trimmed to fit the token budget."""
        schemas = [self._schema(tool) for tool in self._tools.values()]
        if budget_tokens is None:
            return schemas
        for name in TRIM_ORDER:
            if estimate_tokens(schemas) <= budget_tokens:
                break
            if name in NEVER_TRIM:
                continue
            schemas = [schema for schema in schemas if schema["function"]["name"] != name]
        return schemas

    def _schema(self, tool: Tool) -> dict:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }


def estimate_tokens(schemas: list[dict]) -> int:
    """Rough token estimate for a set of tool schemas. M2 replaces this with a real tokenizer."""
    return int(len(json.dumps(schemas)) / CHARS_PER_TOKEN)
