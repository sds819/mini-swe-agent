"""Permission modes, rules and the policy that evaluates them."""

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

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
    ) -> None:
        self.mode = PermissionMode(mode)
        self.rules = list(rules or [])
        self.cwd = Path(cwd).resolve() if cwd else Path.cwd().resolve()
        self.include_dirs = [Path(directory).resolve() for directory in include_dirs or []]

    def check(self, tool: str, params: dict) -> str:
        """Return `allow`, `ask` or `deny`."""
        return self.evaluate(tool, params).decision

    def evaluate(self, tool: str, params: dict) -> Decision:
        """Like `check`, but also reports which rule was hit and why."""
        decision = self._default_decision(tool)
        matched: Rule | None = None
        for rule in self.rules:
            if self._matches(rule, tool, params):
                decision = rule.decision
                matched = rule
        if tool in PATH_TOOLS:
            path = str(params.get("path", ""))
            if path and not self._within_bounds(path):
                if matched and matched.decision == "allow":
                    return Decision("allow", matched, matched.reason)
                return Decision("deny", matched, f"'{path}' is outside the working directory {self.cwd}")
        return Decision(decision, matched, matched.reason if matched else "")

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
        if tool == "bash":
            try:
                return bool(re.search(rule.pattern, str(params.get("command", ""))))
            except re.error:
                return False
        return rule.pattern in ("*", tool)

    def _relative(self, path: str) -> str:
        target = Path(path)
        resolved = (target if target.is_absolute() else self.cwd / target).resolve()
        if resolved.is_relative_to(self.cwd):
            return resolved.relative_to(self.cwd).as_posix()
        return resolved.as_posix()

    def _within_bounds(self, path: str) -> bool:
        target = Path(path)
        resolved = (target if target.is_absolute() else self.cwd / target).resolve()
        if resolved.is_relative_to(self.cwd):
            return True
        return any(resolved.is_relative_to(directory) for directory in self.include_dirs)


def pattern_for(tool: str, params: dict[str, Any]) -> str:
    """The rule pattern that would allow exactly this call."""
    if tool in PATH_TOOLS:
        return str(params.get("path", "*"))
    if tool == "bash":
        return re.escape(str(params.get("command", "")))
    return tool
