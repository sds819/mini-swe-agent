"""Hooks: user defined commands that run at the important moments of a session."""

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from coderagent.config.schema import HookConfig

logger = logging.getLogger("coderagent.hooks")


@dataclass
class HookResult:
    decision: str = ""
    """One of allow, deny, block. Empty means the hook has no opinion."""
    reason: str = ""
    additional_context: str = ""
    updated_input: dict | str | None = None
    """The new input of the event: the arguments of the tool, or the prompt."""


@dataclass
class MergedHookResult:
    """The result of all the hooks of one event, put together."""

    decision: str = ""
    reason: str = ""
    additional_context: str = ""
    updated_input: dict | str | None = None

    @property
    def blocked(self) -> bool:
        return self.decision in ("deny", "block")


def merge_results(results: list[HookResult]) -> MergedHookResult:
    """Any deny wins, the contexts are concatenated, the last updated input wins."""
    merged = MergedHookResult()
    for result in results:
        if result.decision in ("deny", "block"):
            merged.decision = result.decision
            merged.reason = result.reason
        elif result.decision == "allow" and not merged.decision:
            merged.decision = "allow"
        if result.additional_context:
            merged.additional_context = (merged.additional_context + "\n" + result.additional_context).strip()
        if result.updated_input is not None:
            merged.updated_input = result.updated_input
    return merged


class HookRunner:
    """Runs the hook commands of the configuration."""

    def __init__(self, config: HookConfig | None = None, cwd: Path | None = None) -> None:
        self.config = config or HookConfig()
        self.cwd = cwd or Path.cwd()

    def run(self, hook_name: str, payload: dict) -> list[HookResult]:
        """Run every hook that matches this event."""
        results: list[HookResult] = []
        for matcher in self.config.events.get(hook_name, []):
            if not self._matches(matcher.matcher, payload):
                continue
            for hook in matcher.hooks:
                results.append(self._run_one(hook, payload))
        return results

    def apply(self, hook_name: str, payload: dict) -> MergedHookResult:
        """Run the hooks of this event and merge their answers."""
        return merge_results(self.run(hook_name, payload))

    def _matches(self, matcher: str, payload: dict) -> bool:
        if not matcher:
            return True
        tool = payload.get("tool") or ""
        try:
            return re.search(matcher, tool) is not None
        except re.error:
            logger.warning("Hook matcher '%s' is not a valid regex", matcher)
            return False

    def _run_one(self, hook, payload: dict) -> HookResult:
        try:
            completed = subprocess.run(
                hook.command,
                shell=True,
                cwd=self.cwd,
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=hook.timeout,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Hook '%s' timed out, ignoring it", hook.command)
            return HookResult()
        if completed.returncode != 0:
            logger.warning("Hook '%s' failed with %s: %s", hook.command, completed.returncode, completed.stderr.strip())
            return HookResult(decision="deny", reason=completed.stderr.strip()) if hook.strict else HookResult()
        return self._parse(completed.stdout)

    def _parse(self, output: str) -> HookResult:
        if not output.strip():
            return HookResult()
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            logger.warning("Hook output is not JSON, ignoring it: %s", output[:200])
            return HookResult()
        if not isinstance(data, dict):
            return HookResult()
        updated = data.get("updatedInput", data.get("updated_input"))
        return HookResult(
            decision=str(data.get("decision", "")),
            reason=str(data.get("reason", "")),
            additional_context=str(data.get("additionalContext", data.get("additional_context", ""))),
            updated_input=updated if isinstance(updated, (dict, str)) else None,
        )
