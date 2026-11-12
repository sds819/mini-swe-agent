"""The tasks of an eval suite: the format on disk and the parsing of it.

A suite is a directory, every task is a directory inside it. A task has a
`task.yaml` and, next to it, the files that are the initial state of the working
directory of the agent.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from minisweagent.config import get_config_from_spec

TASK_FILE = "task.yaml"
"""The file that describes a task. The other yaml files are part of the fixture."""

DEFAULT_TIMEOUT = 300
DEFAULT_VERIFY_TIMEOUT = 300


@dataclass
class Task:
    id: str
    prompt: str
    verify: list[str] = field(default_factory=list)
    """The commands that decide whether the task passed. A task without one never passes."""
    setup: list[str] = field(default_factory=list)
    """The commands that prepare the working directory, before the agent starts."""
    expect: str = "pass"
    """What the task is supposed to do: `pass` or `fail`.

    A task that must fail keeps the suite honest: a check that never fails
    would let every task pass.
    """
    timeout: int = DEFAULT_TIMEOUT
    """Seconds the agent may spend on the task."""
    verify_timeout: int = DEFAULT_VERIFY_TIMEOUT
    """Seconds each verify command may take."""
    tags: list[str] = field(default_factory=list)
    require_tools: list[str] = field(default_factory=list)
    """The tools the task needs. One of them must have been used successfully.

    A task that changes a file with the `edit` tool and says so cannot be
    solved by another route, so a broken tool shows up as a failed task.
    """
    script: list[dict] = field(default_factory=list)
    """The scripted model. Empty means: the real model."""
    config: list[str] = field(default_factory=list)
    """Config overrides: a path to a yaml file or `a.b=c` specs."""
    path: Path | None = None
    """The directory of the task. Its files are the initial state of the working directory."""


def load_task(directory: Path) -> Task:
    """The task of a directory."""
    directory = Path(directory)
    path = directory / TASK_FILE
    if not path.exists():
        raise FileNotFoundError(f"the task {directory} has no {TASK_FILE}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not data.get("verify"):
        raise ValueError(f"the task {directory} has no verify command: a task without one can never pass")
    expect = str(data.get("expect") or "pass")
    if expect not in ("pass", "fail"):
        raise ValueError(f"the task {directory} expects '{expect}', which is neither 'pass' nor 'fail'")
    return Task(
        id=str(data.get("id") or directory.name),
        prompt=str(data.get("prompt") or ""),
        verify=[str(command) for command in data["verify"]],
        setup=[str(command) for command in data.get("setup") or []],
        expect=expect,
        timeout=int(data.get("timeout") or DEFAULT_TIMEOUT),
        verify_timeout=int(data.get("verify_timeout") or DEFAULT_VERIFY_TIMEOUT),
        tags=[str(tag) for tag in data.get("tags") or []],
        require_tools=[str(tool) for tool in data.get("require_tools") or []],
        script=list(data.get("script") or []),
        config=[str(spec) for spec in data.get("config") or []],
        path=directory,
    )


def load_suite(directory: Path) -> list[Task]:
    """The tasks of a suite, sorted by id."""
    directory = Path(directory)
    if not directory.is_dir():
        raise NotADirectoryError(f"the suite {directory} is not a directory")
    return sorted((load_task(child) for child in directory.iterdir() if child.is_dir()), key=lambda t: t.id)


def task_overrides(task: Task) -> list[dict]:
    """The overrides of a task: a yaml file next to it, or an `a.b=c` spec."""
    overrides = []
    for spec in task.config:
        path = Path(spec)
        if "=" not in spec and not path.is_absolute() and task.path is not None and (task.path / path).exists():
            overrides.append(yaml.safe_load((task.path / path).read_text(encoding="utf-8")) or {})
        else:
            overrides.append(get_config_from_spec(spec))
    return overrides


def task_permission_mode(task: Task) -> str:
    """The permission mode of a task, when the task sets one.

    The mode of the command is the default; a task may ask for another one, so
    that its rules are the ones that count.
    """
    for override in task_overrides(task):
        mode = (override.get("permissions") or {}).get("mode")
        if mode:
            return str(mode)
    return ""


def script_responses(task: Task) -> list[dict]:
    """The script of a task, in the shape the model gateway expects."""
    responses = []
    counter = 0
    for step in task.script:
        calls = []
        for call in step.get("tool_calls") or []:
            counter += 1
            calls.append(
                {
                    "id": f"call_{counter}",
                    "type": "function",
                    "function": {"name": str(call.get("tool") or ""), "arguments": json.dumps(call.get("args") or {})},
                }
            )
        message = {"role": "assistant", "content": str(step.get("content") or ""), "extra": {"cost": 0.0}}
        if calls:
            message["tool_calls"] = calls
        responses.append(message)
    return responses
