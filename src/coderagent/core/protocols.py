"""Protocols for the pluggable parts of the coding agent."""

from collections.abc import Iterator
from typing import Any, Protocol

from coderagent.models.streaming import ModelEvent


class ModelBackend(Protocol):
    """A language model backend."""

    def query(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> dict:
        """Return a normalized assistant message: content, tool_calls and cost."""
        ...

    def query_stream(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> Iterator[ModelEvent]:
        """Yield the answer as it arrives."""
        ...

    def get_template_vars(self) -> dict[str, Any]: ...


class ToolExecutor(Protocol):
    """Turns model tool calls into normalized actions and observations."""

    def plan(self, actions: list[dict]) -> list[dict]:
        """Parse tool calls into normalized actions (tool, tool_call_id, args, raw)."""
        ...

    def execute(self, actions: list[dict]) -> list[dict]:
        """Execute actions and return observation messages, in input order."""
        ...
