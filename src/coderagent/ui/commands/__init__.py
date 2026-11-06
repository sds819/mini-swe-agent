"""The slash commands the user can type.

A command is a function of the context: it reads the core objects and writes its
answer through `context.say`. The UI only has to notice the leading slash and
hand the line over.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from coderagent.config.schema import Config
from coderagent.core.checkpoint import CheckpointStore
from coderagent.core.events import EventBus
from coderagent.core.loop import AgentLoop
from coderagent.core.session import Session, SessionStore
from coderagent.tools.permissions import PermissionPolicy
from coderagent.ui.custom_commands import find_custom, run_custom


@dataclass
class CommandContext:
    """What a command can reach."""

    loop: AgentLoop
    session: Session
    store: SessionStore
    bus: EventBus
    cwd: Path
    config: Config
    policy: PermissionPolicy
    checkpoints: CheckpointStore | None = None
    mcp: Any = None
    """The MCP manager, when one is running."""
    output: Callable[[str], None] = print
    """Where the answer goes."""

    def say(self, text: str) -> None:
        self.output(text)


@dataclass
class Command:
    name: str
    description: str
    handler: Callable[[CommandContext, str], None]
    aliases: list[str] = field(default_factory=list)


COMMANDS: list[Command] = []


def register(command: Command) -> Command:
    COMMANDS.append(command)
    return command


def find(name: str) -> Command | None:
    """The command with this name or one of its aliases."""
    name = name.lstrip("/").lower()
    for command in COMMANDS:
        if command.name == name or name in command.aliases:
            return command
    return None


def load_builtins() -> None:
    """Register the built-in commands. Calling it twice does nothing."""
    if COMMANDS:
        return
    from coderagent.ui.commands import builtin  # noqa: F401


def run(context: CommandContext, line: str) -> bool:
    """Run the command in this line. Returns False when the line is not a command."""
    if not line.startswith("/"):
        return False
    load_builtins()
    name, _, argument = line[1:].partition(" ")
    custom = find_custom(context.cwd, name)
    if custom is not None:
        run_custom(context, custom, argument.strip())
        return True
    command = find(name)
    if command is None:
        context.say(f"Unknown command '/{name}'. Try /help.")
        return True
    command.handler(context, argument.strip())
    return True
