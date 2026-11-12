"""The report of an eval run: the numbers, the fingerprint and the text.

The report is the deliverable of a run: two reports of the same suite can be
compared, as long as their fingerprint is the same. The fingerprint is a hash of
the configuration the agent ran with, so that a change of the harness is visible
instead of being silently mixed into the numbers.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from coderagent.config.schema import Config
from coderagent.eval.runner import TaskResult
from coderagent.eval.task import task_overrides

FORMAT = "coder-eval-1.0"
"""The format of the report. The external tools read it."""


@dataclass
class Report:
    label: str
    suite: str
    model: str
    fingerprint: str
    config: dict[str, Any]
    """The input of the fingerprint, as it was. A diff of it shows what changed."""
    started_at: float
    duration_seconds: float
    tasks: list[TaskResult] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, Any]:
        """The numbers of the whole run."""
        errors = [task for task in self.tasks if task.error_kind]
        graded = [task for task in self.tasks if not task.error_kind]
        passed = [task for task in graded if task.passed]
        unexpected = [task for task in self.tasks if not task.as_expected]
        return {
            "tasks": len(self.tasks),
            "passed": len(passed),
            "failed": len(graded) - len(passed),
            "errors": len(errors),
            "unexpected": len(unexpected),
            "pass_rate": round(len(passed) / len(graded), 4) if graded else 0.0,
            "total_cost": round(sum(task.cost for task in self.tasks), 6),
            "total_tokens_in": sum(task.tokens_in for task in self.tasks),
            "total_tokens_out": sum(task.tokens_out for task in self.tasks),
            "total_model_calls": sum(task.model_calls for task in self.tasks),
            "total_tool_calls": sum(task.tool_calls for task in self.tasks),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "label": self.label,
            "suite": self.suite,
            "model": self.model,
            "fingerprint": self.fingerprint,
            "config": self.config,
            "started_at": self.started_at,
            "duration_seconds": self.duration_seconds,
            "summary": self.summary,
            "tasks": [task.to_dict() for task in self.tasks],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_text(self) -> str:
        """The report, as a table a human reads."""
        lines = [
            f"suite: {self.suite}  model: {self.model}  label: {self.label or '-'}",
            f"fingerprint: {self.fingerprint}",
        ]
        for task in self.tasks:
            mark = "✓" if task.passed else "✗"
            if not task.as_expected:
                mark = "!"
            note = f"  {task.error}" if task.error else ""
            lines.append(
                f"{mark} {task.id:<24} {task.mode:<8} ${task.cost:.4f}  "
                f"{task.model_calls:>3} calls  {task.tool_calls:>3} tools  {task.duration_seconds:>6.1f}s{note}"
            )
        summary = self.summary
        lines.append(
            f"{summary['tasks']} tasks: {summary['passed']} passed, {summary['failed']} failed, "
            f"{summary['errors']} errors (pass rate {summary['pass_rate'] * 100:.1f}%)"
        )
        if summary["unexpected"]:
            lines.append(f"{summary['unexpected']} tasks did not do what they were supposed to do")
        lines.append(
            f"cost ${summary['total_cost']:.4f}  tokens {summary['total_tokens_in']} in / "
            f"{summary['total_tokens_out']} out  {summary['total_model_calls']} model calls"
        )
        return "\n".join(lines)


def fingerprint_inputs(config: Config, model: str, permission_mode: str = "", tasks=None) -> dict[str, Any]:
    """The configuration the numbers depend on. The hash of it is the fingerprint."""
    return {
        "format": FORMAT,
        "model": model,
        "model.routing": config.model.routing,
        "model.routing_rules": [rule.model_dump() for rule in config.model.routing_rules],
        "agent.system_prompt": config.agent.system_prompt,
        "agent.max_turns": config.agent.max_turns,
        "agent.cost_limit": config.agent.cost_limit,
        "agent.token_limit": config.agent.token_limit,
        "tools.enabled": config.tools.enabled,
        "tools.disabled": config.tools.disabled,
        "permissions.mode": permission_mode or config.permissions.mode,
        "permissions.rules": config.permissions.rules,
        "permissions.deny_paths": config.permissions.deny_paths,
        "context": config.context.model_dump(),
        "sandbox.type": config.sandbox.type,
        "tasks": {task.id: task_overrides(task) for task in tasks or []},
        "tasks.require_tools": {
            task.id: [requirement.to_dict() for requirement in task.require_tools] for task in tasks or []
        },
    }


def fingerprint(config: Config, model: str, permission_mode: str = "", tasks=None) -> str:
    """The hash of the configuration the agent runs with."""
    payload = json.dumps(fingerprint_inputs(config, model, permission_mode, tasks), sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
