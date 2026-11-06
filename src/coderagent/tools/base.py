"""Tool abstractions shared by every tool implementation."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from coderagent.config.schema import ToolConfig
from coderagent.core.events import EventBus
from coderagent.core.session import Session
from coderagent.tools.permissions import PermissionPolicy


@dataclass
class ToolResult:
    content: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolContext:
    cwd: Path
    session: Session
    bus: EventBus
    policy: PermissionPolicy
    config: ToolConfig
    env: Any = None
    """Execution environment for tools that need to run commands."""
    background: dict[str, Any] = field(default_factory=dict)
    """Background shell tasks, keyed by task id."""


class Tool(Protocol):
    name: str
    description: str
    parameters: dict[str, Any]
    """JSON Schema of the tool's arguments."""

    def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult: ...


def resolve_path(ctx: ToolContext, path: str) -> Path:
    """Resolve a tool argument against the session's working directory."""
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ctx.cwd / candidate


__all__ = ["Tool", "ToolContext", "ToolResult", "resolve_path"]
