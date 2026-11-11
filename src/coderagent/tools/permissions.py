"""Permission modes, rules and the policy that evaluates them."""

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from coderagent.tools import bash_policy

READ_TOOLS = {"read", "glob", "grep", "ls"}
WRITE_TOOLS = {"write", "edit", "multi_edit"}
INFO_TOOLS = {"todo_write", "bash_output", "bash_kill"}
"""Tools that only touch the agent's own bookkeeping, so they never need approval."""
PATH_TOOLS = READ_TOOLS | WRITE_TOOLS


class PermissionMode(str, Enum):
    DEFAULT = "default"
    ACCEPT_EDITS = "acceptEdits"
    PLAN = "plan"
    BYPASS = "bypass"
    READONLY = "readonly"


@dataclass
class Rule:
    tool: str = "*"
    pattern: str = "*"
    """Glob for path tools, regular expression for `bash`, tool name otherwise."""
    decision: str = "ask"
    reason: str = ""


@dataclass
class Decision:
    decision: str
    rule: Rule | None = None
    reason: str = ""


class ApprovalDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ALWAYS = "always"


MODE_NOTES = {
    PermissionMode.PLAN: (
        "You are in plan mode. You may only look around: `read`, `glob`, `grep` and `ls` work, "
        "but every tool that changes something, `bash` included, is refused. Investigate the task "
        "and answer with the plan you would follow. The user decides whether it is executed."
    ),
    PermissionMode.READONLY: (
        "You are in read-only mode. You may only look around: `read`, `glob`, `grep` and `ls` work, "
        "but every tool that changes something, `bash` included, is refused. Answer with what you "
        "found and describe the change you would make, but do not make it."
    ),
}
"""What the model is told when the mode takes tools away from it."""


def mode_note(mode: PermissionMode) -> str:
    """The note for the model, empty when the mode needs no explanation."""
    return MODE_NOTES.get(PermissionMode(mode), "")


def mode_block(mode: PermissionMode) -> str:
    """The note as the block the model sees, empty when the mode needs no explanation."""
    note = mode_note(mode)
    if not note:
        return ""
    return f'<permission_mode mode="{PermissionMode(mode).value}">\n{note}\n</permission_mode>'


class Approver(Protocol):
    def request(self, tool: str, params: dict, reason: str) -> ApprovalDecision: ...


class HeadlessApprover:
    """Without a terminal there is nobody to ask, so approval-required calls are denied."""

    def __init__(self, allow: bool = False) -> None:
        self.allow = allow

    def request(self, tool: str, params: dict, reason: str) -> ApprovalDecision:
        return ApprovalDecision.ALLOW if self.allow else ApprovalDecision.DENY


def glob_to_regex(pattern: str) -> re.Pattern:
    """Translate a glob into a regex where `*` does not cross `/` but `**` does."""
    parts = ["^"]
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            parts.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            parts.append(".*")
            index += 2
        elif pattern[index] == "*":
            parts.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            parts.append("[^/]")
            index += 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    parts.append("$")
    return re.compile("".join(parts))


class PermissionPolicy:
    """Decides whether a tool call is allowed, needs approval or is denied."""

    def __init__(
        self,
        mode: PermissionMode = PermissionMode.DEFAULT,
        rules: list[Rule] | None = None,
        *,
        cwd: Path | None = None,
        include_dirs: list[str] | None = None,
        bounded: bool = True,
    ) -> None:
        self.mode = PermissionMode(mode)
        self.rules = list(rules or [])
        self.cwd = Path(cwd).resolve() if cwd else Path.cwd().resolve()
        self.include_dirs = [Path(directory).resolve() for directory in include_dirs or []]
        self.bounded = bounded
        """Whether the commands run on this disk. A container has its own boundary."""

    def check(self, tool: str, params: dict) -> str:
        """Return `allow`, `ask` or `deny`."""
        return self.evaluate(tool, params).decision

    def evaluate(self, tool: str, params: dict) -> Decision:
        """Like `check`, but also reports which rule was hit and why."""
        if tool == "bash":
            return self._evaluate_bash(str(params.get("command", "")))
        decision = self._default_decision(tool)
        matched: Rule | None = None
        for rule in self.rules:
            if self._matches(rule, tool, params):
                decision = rule.decision
                matched = rule
        if tool in PATH_TOOLS:
            path = str(params.get("path", ""))
            if path and not self.within_bounds(path):
                """A rule cannot open the disk: the bounds hold in every mode."""
                return Decision("deny", matched, self._outside_reason(path))
        return Decision(decision, matched, matched.reason if matched else "")

    def _evaluate_bash(self, command: str) -> Decision:
        """The decision for a shell command.

        Every part of the command is judged on its own and the strictest part
        wins: an allowed `pytest` does not carry a `rm` along with it. A path
        that leaves the working directory is refused in every mode.
        """
        outside = bash_policy.outside_paths(command, self.cwd, self.include_dirs) if self.bounded else []
        if outside:
            """The bounds of the disk hold in every mode, like they do for the file tools."""
            return Decision("deny", None, self._outside_reason(outside[0]))
        if self.mode == PermissionMode.BYPASS:
            return Decision("allow", None, "")
        if self.mode in (PermissionMode.PLAN, PermissionMode.READONLY):
            return Decision("deny", None, "")
        decision, matched, reason = "allow", None, ""
        for segment in bash_policy.segments(command):
            rule = self._bash_rule(segment)
            if rule is not None:
                decision = _strictest(decision, rule.decision)
                matched = rule
                reason = rule.reason or reason
                continue
            kind, why = bash_policy.classify_segment(segment)
            if kind == "dangerous":
                decision = _strictest(decision, "ask")
                reason = reason or why
            elif kind == "unknown":
                decision = _strictest(decision, "ask")
        return Decision(decision, matched, reason)

    def _bash_rule(self, segment: str) -> Rule | None:
        """The last rule that matches a part of the command."""
        matched = None
        for rule in self.rules:
            if rule.tool not in ("*", "bash"):
                continue
            if _matches_bash(rule.pattern, segment):
                matched = rule
        return matched

    def _default_decision(self, tool: str) -> str:
        if self.mode == PermissionMode.BYPASS:
            return "allow"
        if tool in READ_TOOLS | INFO_TOOLS:
            return "allow"
        if self.mode in (PermissionMode.PLAN, PermissionMode.READONLY):
            return "deny"
        if self.mode == PermissionMode.ACCEPT_EDITS:
            return "allow" if tool in WRITE_TOOLS else "ask"
        return "ask"

    def _matches(self, rule: Rule, tool: str, params: dict) -> bool:
        if rule.tool not in ("*", tool):
            return False
        if tool in PATH_TOOLS:
            path = str(params.get("path", ""))
            if not path:
                return rule.pattern == "*"
            return bool(glob_to_regex(rule.pattern).match(self._relative(path)))
        return rule.pattern in ("*", tool)

    def _relative(self, path: str) -> str:
        target = Path(path)
        resolved = (target if target.is_absolute() else self.cwd / target).resolve()
        if resolved.is_relative_to(self.cwd):
            return resolved.relative_to(self.cwd).as_posix()
        return resolved.as_posix()

    def within_bounds(self, path: str) -> bool:
        """Whether a path is inside the working directory or one of the extra directories.

        The rules of the user cannot widen this: an `allow` rule for a path outside
        the bounds is still a path the agent must not touch.
        """
        target = Path(path)
        resolved = (target if target.is_absolute() else self.cwd / target).resolve()
        if resolved.is_relative_to(self.cwd):
            return True
        return any(resolved.is_relative_to(directory) for directory in self.include_dirs)

    def _outside_reason(self, path: str) -> str:
        """Why the path is refused, and where it would be allowed."""
        reason = f"'{path}' is outside the working directory {self.cwd}"
        if self.include_dirs:
            directories = ", ".join(str(directory) for directory in self.include_dirs)
            return f"{reason}. The directories that are open: {directories}"
        return reason


def pattern_for(tool: str, params: dict[str, Any]) -> str:
    """The rule pattern that would allow exactly this call."""
    if tool in PATH_TOOLS:
        return str(params.get("path", "*"))
    if tool == "bash":
        """A rule is matched against a part of the command, so the rule names the first one."""
        parts = bash_policy.segments(str(params.get("command", "")))
        return re.escape(parts[0]) if parts else "*"
    return tool


def _matches_bash(pattern: str, segment: str) -> bool:
    """Whether the pattern of a rule is the beginning of a part of the command.

    A rule is about a command, not about a word somewhere in a line: `git push`
    does not match `echo "git push"`.
    """
    if pattern == "*":
        return True
    try:
        return bool(re.match(pattern, segment))
    except re.error:
        return False


def _strictest(first: str, second: str) -> str:
    """The stricter of two decisions."""
    order = {"allow": 0, "ask": 1, "deny": 2}
    return first if order.get(first, 1) >= order.get(second, 1) else second
