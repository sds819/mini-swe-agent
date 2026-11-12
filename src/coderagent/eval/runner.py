"""The runner of an eval suite: the working directory, the agent, the verify commands.

Every task runs on its own: its own working directory, its own session, its own
model. The suite only tells whether the tasks passed and what they cost.
"""

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from coderagent.config.schema import Config
from coderagent.core.sandbox import build_environment
from coderagent.core.session import SessionStore
from coderagent.core.telemetry import collect
from coderagent.eval.task import Task, script_responses
from coderagent.run import build_loop, build_model
from coderagent.testing.factory import AllowAllApprover
from coderagent.testing.scripted_model import ScriptedModel
from coderagent.tools.permissions import ApprovalDecision
from minisweagent.config import get_config_from_spec
from minisweagent.utils.serialize import recursive_merge

SCRIPT_ERROR = "ran out of responses"
"""What the scripted model says when the script is too short."""


@dataclass
class VerifyResult:
    command: str
    exit_code: int
    output: str
    timed_out: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "output": self.output,
        }


@dataclass
class TaskResult:
    id: str
    mode: str
    """`scripted` or `live`."""
    passed: bool
    """The verify commands decided it. A task whose harness broke never passes."""
    expect: str = "pass"
    """What the task was supposed to do: `pass` or `fail`."""
    as_expected: bool = True
    """Whether the task did what it was supposed to do."""
    stop_reason: str = ""
    error: str = ""
    error_kind: str = ""
    """`setup` or `script` when the harness failed, empty when the agent did."""
    cost: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    model_calls: int = 0
    """The calls of the main loop. The calls of the sub agents are not in it."""
    tool_calls: int = 0
    tool_errors: int = 0
    approvals: int = 0
    compactions: int = 0
    duration_seconds: float = 0.0
    session_id: str = ""
    setup: list[VerifyResult] = field(default_factory=list)
    verify: list[VerifyResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "mode": self.mode,
            "passed": self.passed,
            "expect": self.expect,
            "as_expected": self.as_expected,
            "stop_reason": self.stop_reason,
            "error": self.error,
            "error_kind": self.error_kind,
            "cost": self.cost,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "tool_errors": self.tool_errors,
            "approvals": self.approvals,
            "compactions": self.compactions,
            "duration_seconds": self.duration_seconds,
            "session_id": self.session_id,
            "setup": [result.to_dict() for result in self.setup],
            "verify": [result.to_dict() for result in self.verify],
        }


class CountingApprover(AllowAllApprover):
    """Approves everything, but counts how often a human would have been needed."""

    def __init__(self) -> None:
        self.count = 0

    def request(self, tool: str, params: dict, reason: str) -> ApprovalDecision:
        self.count += 1
        return super().request(tool, params, reason)


def run_commands(commands: list[str], environment, timeout: int) -> list[VerifyResult]:
    """Run the commands of a task and report what each of them did.

    The commands run in the environment of the agent, without the permission layer:
    the verify of a task needs the raw exit code and the raw output.
    """
    results = []
    for command in commands:
        outcome = environment.execute({"command": command}, timeout=timeout)
        output = str(outcome.get("output") or "")
        exception = str(outcome.get("exception_info") or "")
        results.append(
            VerifyResult(
                command=command,
                exit_code=int(outcome.get("returncode", 0)),
                output=(output + ("\n" + exception if exception else "")).strip(),
                timed_out="timed out" in exception.lower(),
            )
        )
    return results


def prepare_workdir(task: Task, workdir: Path) -> Path:
    """The working directory of a task: the fixture of the task, and nothing else."""
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    if task.path is None:
        return workdir
    for source in sorted(task.path.rglob("*")):
        if source.suffix in (".yaml", ".yml"):
            """The yaml files describe the task, they are not part of the fixture."""
            continue
        target = workdir / source.relative_to(task.path)
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return workdir


def task_config(base: Config, task: Task) -> Config:
    """The configuration of a task: the one of the run, plus the overrides of the task."""
    config = base.model_copy(deep=True)
    explicit = "context_window" in base.context.model_fields_set
    for spec in task.config:
        override = _override(spec, task)
        explicit = explicit or "context_window" in (override.get("context") or {})
        config = Config(**recursive_merge(config.model_dump(mode="json"), override))
    if not explicit:
        """The window of the model is used when the configuration does not set one."""
        config.context.model_fields_set.discard("context_window")
    return config


def _override(spec: str, task: Task) -> dict:
    """The override of a task: a yaml file next to it, or an `a.b=c` spec."""
    path = Path(spec)
    if "=" not in spec and not path.is_absolute() and task.path is not None and (task.path / path).exists():
        return yaml.safe_load((task.path / path).read_text(encoding="utf-8")) or {}
    return get_config_from_spec(spec)


def run_task(
    task: Task,
    config: Config,
    *,
    workdir: Path,
    store: SessionStore,
    permission_mode: str = "bypass",
    approver=None,
    user_home: Path | None = None,
) -> TaskResult:
    """Run one task: the fixture, the agent, the verify commands."""
    mode = "scripted" if task.script else "live"
    prepare_workdir(task, workdir)
    environment = build_environment(config.sandbox, workdir)
    setup = run_commands(task.setup, environment, task.verify_timeout)
    if any(result.exit_code != 0 for result in setup):
        failed = next(result for result in setup if result.exit_code != 0)
        return TaskResult(
            id=task.id,
            mode=mode,
            passed=False,
            expect=task.expect,
            as_expected=False,
            stop_reason="setup_failed",
            error=f"the setup failed: {failed.command}",
            error_kind="setup",
            setup=setup,
        )
    config = task_config(config, task)
    if task.script:
        """A scripted model answers every question, so nothing may be routed or compacted."""
        config.model.routing = {}
        config.model.routing_rules = []
        config.context.auto_compact = False
    approver = approver or (CountingApprover() if permission_mode == "default" else None)
    model = ScriptedModel(script_responses(task)) if task.script else build_model(config)
    loop = build_loop(
        config,
        workdir,
        model=model,
        store=store,
        permission_mode=permission_mode,
        approver=approver,
        user_home=user_home,
    )
    deadline = time.monotonic() + task.timeout
    loop.cancel = lambda: time.monotonic() > deadline
    started = time.monotonic()
    result = loop.run_turn(task.prompt)
    duration = time.monotonic() - started
    events = store.events(result.session_id)
    metrics = collect(events)
    verify = run_commands(task.verify, loop.sandbox, task.verify_timeout)
    script_error = result.stop_reason == "error" and SCRIPT_ERROR in result.error
    error_kind = "script" if script_error else ""
    passed = not error_kind and bool(task.verify) and all(item.exit_code == 0 for item in verify)
    return TaskResult(
        id=task.id,
        mode=mode,
        passed=passed,
        expect=task.expect,
        as_expected=not error_kind and passed == (task.expect == "pass"),
        stop_reason=result.stop_reason,
        error=result.error,
        error_kind=error_kind,
        cost=metrics.total_cost,
        tokens_in=metrics.total_tokens_in,
        tokens_out=metrics.total_tokens_out,
        model_calls=metrics.model_calls,
        tool_calls=metrics.tool_calls,
        tool_errors=_tool_errors(events),
        approvals=getattr(approver, "count", 0),
        compactions=metrics.compactions,
        duration_seconds=duration,
        session_id=result.session_id,
        setup=setup,
        verify=verify,
    )


def run_suite(
    tasks: list[Task],
    config: Config,
    *,
    root: Path,
    store: SessionStore,
    permission_mode: str = "bypass",
    user_home: Path | None = None,
) -> list[TaskResult]:
    """Run every task of a suite, each one in its own working directory."""
    return [
        run_task(
            task,
            config,
            workdir=root / task.id,
            store=store,
            permission_mode=permission_mode,
            user_home=user_home,
        )
        for task in tasks
    ]


def _tool_errors(events) -> int:
    """The tool calls that failed, the denied ones included."""
    count = 0
    for event in events:
        if event.type != "tool_result":
            continue
        for message in event.payload.get("messages") or []:
            if str(message.get("content") or "").startswith("Error:"):
                count += 1
    return count
