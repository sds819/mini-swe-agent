"""Custom commands: a markdown file per command in `.coderagent/commands`."""

from pathlib import Path

from coderagent.config.schema import Config
from coderagent.core.events import EventBus
from coderagent.core.loop import AgentLoop
from coderagent.core.session import SessionStore
from coderagent.models.gateway import ModelGateway
from coderagent.testing.factory import build_executor
from coderagent.testing.scripted_model import ScriptedModel
from coderagent.tools.permissions import PermissionMode, PermissionPolicy
from coderagent.ui.commands import CommandContext, run
from coderagent.ui.custom_commands import find_custom, load_custom_commands, restricted_registry

COMMAND = """---
description: Generate a commit message
argument-hint: [file]
allowed-tools: bash(git diff:*), read
---
Describe the change of $1.
Everything else: $ARGUMENTS
"""


def _write(tmp_path, name: str = "commit.md", text: str = COMMAND) -> Path:
    directory = tmp_path / ".coderagent" / "commands"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def _context(tmp_path, responses=None) -> tuple[CommandContext, list[str]]:
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    bus = EventBus()
    executor = build_executor(tmp_path)
    loop = AgentLoop(
        ModelGateway(ScriptedModel(responses or [{"role": "assistant", "content": "done"}])),
        executor,
        session,
        store,
        bus,
        tools=executor.registry.schemas(),
    )
    output: list[str] = []
    context = CommandContext(
        loop=loop,
        session=session,
        store=store,
        bus=bus,
        cwd=Path(tmp_path),
        config=Config(),
        policy=PermissionPolicy(PermissionMode.BYPASS, [], cwd=Path(tmp_path)),
        output=output.append,
    )
    return context, output


def test_the_commands_of_the_project_are_found(tmp_path):
    _write(tmp_path)
    commands = load_custom_commands(tmp_path)
    assert [command.name for command in commands] == ["commit"]
    assert commands[0].description == "Generate a commit message"
    assert commands[0].argument_hint == "[file]"


def test_a_file_without_front_matter_is_ignored(tmp_path):
    _write(tmp_path, "plain.md", "just a prompt")
    assert load_custom_commands(tmp_path) == []


def test_the_arguments_are_filled_in(tmp_path):
    _write(tmp_path)
    command = find_custom(tmp_path, "commit")
    assert command.render("a.py b.py") == "Describe the change of a.py.\nEverything else: a.py b.py"


def test_a_missing_argument_leaves_a_gap(tmp_path):
    _write(tmp_path)
    assert "Describe the change of ." in find_custom(tmp_path, "commit").render("")


def test_the_allowed_tools_are_read(tmp_path):
    _write(tmp_path)
    command = find_custom(tmp_path, "commit")
    assert command.tool_names() == ["bash", "read"]


def test_the_registry_can_be_restricted(tmp_path):
    context, output = _context(tmp_path)
    registry = context.loop.executor.registry
    assert set(restricted_registry(registry, ["read"]).names()) == {"read"}


def test_a_custom_command_runs_the_model(tmp_path):
    _write(tmp_path)
    context, output = _context(tmp_path)
    assert run(context, "/commit a.py") is True
    assert output == ["done"]
    assert context.loop.context.history.messages[0]["content"].startswith("Describe the change of a.py")


def test_a_custom_command_only_gets_the_allowed_tools(tmp_path):
    _write(tmp_path)
    context, output = _context(tmp_path)
    seen: list[list[str]] = []

    class Watcher(ScriptedModel):
        def query(self, messages, tools=None, **kwargs):
            seen.append([schema["function"]["name"] for schema in tools or []])
            return {"role": "assistant", "content": "done"}

    context.loop.model.backend = Watcher()
    run(context, "/commit a.py")
    assert seen == [["bash", "read"]]


def test_the_tools_are_given_back_afterwards(tmp_path):
    _write(tmp_path)
    context, output = _context(tmp_path)
    before = context.loop.executor.registry.names()
    run(context, "/commit a.py")
    assert context.loop.executor.registry.names() == before
