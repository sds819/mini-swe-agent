"""The comparison of two eval reports: did the change of the harness make the agent worse?

Two runs of the same suite are only comparable when they ran the same tasks. The
comparison therefore looks at the tasks that both runs have, and it says what
changed: a task that used to pass and does not pass any more is a regression.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Comparison:
    before_label: str
    after_label: str
    before_fingerprint: str
    after_fingerprint: str
    compared: list[str] = field(default_factory=list)
    """The tasks both runs have."""
    graded: list[str] = field(default_factory=list)
    """The tasks of both runs that are a rate, the guards excluded."""
    regressions: list[str] = field(default_factory=list)
    """The tasks that passed before and do not pass any more."""
    improvements: list[str] = field(default_factory=list)
    """The tasks that did not pass before and pass now."""
    only_before: list[str] = field(default_factory=list)
    only_after: list[str] = field(default_factory=list)
    before_pass_rate: float = 0.0
    after_pass_rate: float = 0.0
    before_summary: dict[str, Any] = field(default_factory=dict)
    after_summary: dict[str, Any] = field(default_factory=dict)
    unexpected: list[str] = field(default_factory=list)
    """The tasks of the second run that did not do what they were supposed to do."""

    @property
    def config_changed(self) -> bool:
        """Whether the two runs ran a different configuration."""
        return self.before_fingerprint != self.after_fingerprint

    @property
    def drop(self) -> float:
        """How much the pass rate fell."""
        return round(self.before_pass_rate - self.after_pass_rate, 4)


def compare(before: dict[str, Any], after: dict[str, Any]) -> Comparison:
    """The comparison of two reports."""
    old = {task["id"]: task for task in before.get("tasks") or []}
    new = {task["id"]: task for task in after.get("tasks") or []}
    comparison = Comparison(
        before_label=str(before.get("label") or ""),
        after_label=str(after.get("label") or ""),
        before_fingerprint=str(before.get("fingerprint") or ""),
        after_fingerprint=str(after.get("fingerprint") or ""),
        before_summary=dict(before.get("summary") or {}),
        after_summary=dict(after.get("summary") or {}),
    )
    for task_id in sorted(set(old) | set(new)):
        if task_id not in new:
            comparison.only_before.append(task_id)
        elif task_id not in old:
            comparison.only_after.append(task_id)
        else:
            comparison.compared.append(task_id)
    graded = [task_id for task_id in comparison.compared if _expectation(old[task_id], new[task_id]) == "pass"]
    comparison.graded = graded
    comparison.before_pass_rate = _rate(old, graded)
    comparison.after_pass_rate = _rate(new, graded)
    for task_id in comparison.compared:
        if _expectation(old[task_id], new[task_id]) != "pass":
            """A task that must fail keeps the suite honest, its result is not a rate."""
            continue
        was, now = bool(old[task_id].get("passed")), bool(new[task_id].get("passed"))
        if was and not now:
            comparison.regressions.append(task_id)
        elif now and not was:
            comparison.improvements.append(task_id)
    comparison.unexpected = [task["id"] for task in new.values() if not task.get("as_expected", True)]
    return comparison


def _expectation(old: dict[str, Any], new: dict[str, Any]) -> str:
    """What the task was supposed to do.

    The reports of the old harness have no field, so the other run decides.
    """
    return str(new.get("expect") or old.get("expect") or "pass")


def _rate(tasks: dict[str, dict[str, Any]], ids: list[str]) -> float:
    if not ids:
        return 0.0
    return round(sum(1 for task_id in ids if tasks[task_id].get("passed")) / len(ids), 4)


def check(report: dict[str, Any]) -> list[str]:
    """The problems of a single run: the tasks that did not do what they were supposed to."""
    problems = []
    unexpected = [task["id"] for task in report.get("tasks") or [] if not task.get("as_expected", True)]
    if unexpected:
        problems.append(
            f"{len(unexpected)} of the tasks did not do what they were supposed to do: {', '.join(unexpected)}"
        )
    errors = [task["id"] for task in report.get("tasks") or [] if task.get("error_kind")]
    if errors:
        problems.append(f"{len(errors)} of the tasks the harness could not grade: {', '.join(errors)}")
    return problems


def verdict(comparison: Comparison, max_regressions: int = 0, max_drop: float = 0.0) -> list[str]:
    """The problems of the change: what the agent cannot do any more."""
    problems = []
    if len(comparison.regressions) > max_regressions:
        problems.append(
            f"{len(comparison.regressions)} regressions (at most {max_regressions} allowed): "
            f"{', '.join(comparison.regressions)}"
        )
    if comparison.drop > max_drop:
        problems.append(
            f"the pass rate fell from {comparison.before_pass_rate:.3f} to {comparison.after_pass_rate:.3f} "
            f"(a drop of {comparison.drop:.3f}, at most {max_drop:.3f} allowed)"
        )
    return problems


def render(comparison: Comparison) -> str:
    """The comparison, as a text a human reads."""
    lines = [
        f"before: {comparison.before_label or '-'}  fingerprint: {comparison.before_fingerprint or '-'}",
        f"after:  {comparison.after_label or '-'}  fingerprint: {comparison.after_fingerprint or '-'}",
    ]
    if comparison.before_fingerprint:
        if comparison.config_changed:
            lines.append("the configuration changed between the two runs")
        else:
            lines.append("the two runs ran the same configuration")
    if comparison.compared:
        lines.append(
            f"pass rate: {comparison.before_pass_rate:.3f} -> {comparison.after_pass_rate:.3f} "
            f"over {len(comparison.graded)} tasks of both runs"
        )
        for title, ids in (
            ("regressions", comparison.regressions),
            ("improvements", comparison.improvements),
            ("guards", [task_id for task_id in comparison.compared if task_id not in comparison.graded]),
            ("only in the first run", comparison.only_before),
            ("only in the second run", comparison.only_after),
        ):
            lines.append(f"{title}: {', '.join(ids) if ids else '-'}")
    else:
        lines.append("there is no run to compare with, only the report of the second run")
    lines.append(_summary_line(comparison.after_summary))
    lines.append(f"unexpected: {', '.join(comparison.unexpected) if comparison.unexpected else '-'}")
    return "\n".join(lines)


def _summary_line(summary: dict[str, Any]) -> str:
    """The numbers of a run, as one line."""
    if not summary:
        return "no numbers"
    return (
        f"{summary.get('tasks', 0)} tasks: {summary.get('passed', 0)} passed, "
        f"{summary.get('failed', 0)} failed, {summary.get('errors', 0)} errors, "
        f"{summary.get('unexpected', 0)} unexpected"
    )
