"""Custom commands: a markdown file per command in `.coderagent/commands`.

The file starts with front matter, the way Claude Code does it:

    ---
    description: Generate a commit message
    argument-hint: [file]
    allowed-tools: bash(git diff:*), read
    ---
    Describe the change of $1 and use $ARGUMENTS for everything else.
"""

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from coderagent.tools.registry import ToolRegistry

COMMANDS_DIR = Path(".coderagent") / "commands"


@dataclass
class CustomCommand:
    name: str
    description: str = ""
    argument_hint: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    """The tools the command may use. Empty means all of them."""
    model: str = ""
    """The model to use for this command. Empty means the one of the session."""
    body: str = ""
    """The prompt that is sent to the model."""
    path: Path | None = None

    def render(self, arguments: str) -> str:
        """The prompt, with the arguments filled in."""
        parts = shlex.split(arguments) if arguments else []
        text = self.body.replace("$ARGUMENTS", arguments)
        return re.sub(
            r"\$(\d+)",
            lambda match: parts[int(match.group(1)) - 1] if int(match.group(1)) <= len(parts) else "",
            text,
        )

    def tool_names(self) -> list[str]:
        """The names of the tools the command may use."""
        return [spec.split("(")[0].strip() for spec in self.allowed_tools]


def load_custom_commands(cwd: Path) -> list[CustomCommand]:
    """The custom commands of this project."""
    directory = Path(cwd) / COMMANDS_DIR
    if not directory.is_dir():
        return []
    commands = []
    for path in sorted(directory.glob("*.md")):
        command = parse_custom_command(path)
        if command is not None:
            commands.append(command)
    return commands


def parse_custom_command(path: Path) -> CustomCommand | None:
    """Read one command file. Returns None when the file cannot be used."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    _, _, rest = text.partition("---")
    front_matter, _, body = rest.partition("---")
    try:
        data: dict[str, Any] = yaml.safe_load(front_matter) or {}
    except yaml.YAMLError:
        return None
    return CustomCommand(
        name=path.stem,
        description=str(data.get("description", "")),
        argument_hint=_hint(data.get("argument-hint", "")),
        allowed_tools=_split_tools(data.get("allowed-tools", "")),
        model=str(data.get("model", "")),
        body=body.strip(),
        path=path,
    )


def _hint(value: Any) -> str:
    """The argument hint, as a string. A list becomes `[a b]`."""
    if isinstance(value, list):
        return "[" + " ".join(str(item) for item in value) + "]"
    return str(value)


def _split_tools(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def find_custom(cwd: Path, name: str) -> CustomCommand | None:
    """The custom command with this name."""
    name = name.lstrip("/").lower()
    return next((command for command in load_custom_commands(cwd) if command.name.lower() == name), None)


def restricted_registry(registry: ToolRegistry, allowed: list[str]) -> ToolRegistry:
    """A registry with only the allowed tools, in the order they were allowed."""
    tools = [registry.get(name.split("(")[0].strip()) for name in allowed]
    return ToolRegistry([tool for tool in tools if tool is not None])


def run_custom(context, command: CustomCommand, arguments: str) -> None:
    """Run a custom command: the prompt goes to the model, with the tools it may use."""
    from coderagent.models.backends import LiteLLMBackend

    loop = context.loop
    original_registry = loop.executor.registry
    original_tools = loop.tools
    original_backend = loop.model.backend
    try:
        if command.allowed_tools:
            loop.executor.registry = restricted_registry(original_registry, command.allowed_tools)
            loop.tools = loop.executor.registry.schemas()
        if command.model:
            loop.model.backend = LiteLLMBackend(command.model, model_kwargs=context.config.model.model_kwargs)
        result = loop.run_turn(command.render(arguments))
    finally:
        loop.executor.registry = original_registry
        loop.tools = original_tools
        loop.model.backend = original_backend
    answer = next(
        (message.get("content", "") for message in reversed(result.messages) if message.get("role") == "assistant"), ""
    )
    context.say(answer or f"The command finished with {result.stop_reason}.")
