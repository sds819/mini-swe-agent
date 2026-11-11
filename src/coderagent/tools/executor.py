"""Executor: model tool calls -> permission check -> tool run -> observation messages."""

import json
import time
from concurrent.futures import ThreadPoolExecutor

from coderagent.core.events import Event, EventType
from coderagent.core.session import SessionState
from coderagent.tools.base import ToolContext, ToolResult
from coderagent.tools.permissions import (
    WRITE_TOOLS,
    ApprovalDecision,
    Approver,
    PermissionPolicy,
    pattern_for,
)
from coderagent.tools.registry import ToolRegistry

SEQUENTIAL_TOOLS = {"bash", "write", "edit", "multi_edit"}


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        policy: PermissionPolicy,
        ctx_factory,
        approver: Approver | None = None,
        *,
        rules_home=None,
        on_path=None,
        before_write=None,
        hooks=None,
        store=None,
    ) -> None:
        self.registry = registry
        self.policy = policy
        self.ctx_factory = ctx_factory
        self.approver = approver
        self.rules_home = rules_home
        self.on_path = on_path
        """Called with the path of every path based tool, so the engine can pick up instructions."""
        self.before_write = before_write
        """Called with (tool, params) before a write tool runs, e.g. to take a checkpoint."""
        self.hooks = hooks
        """The hook runner, when the session has hooks."""
        self.store = store
        """The event log. The result of a tool is written to it, with its diff."""

    def plan(self, actions: list[dict]) -> list[dict]:
        """Parse raw tool calls into normalized actions."""
        planned = []
        for call in actions:
            function = call.get("function") or {}
            name = function.get("name") or call.get("name") or ""
            raw_arguments = function.get("arguments", call.get("arguments", "{}"))
            action = {
                "tool": name,
                "tool_call_id": call.get("id", ""),
                "args": {},
                "raw": call,
            }
            if isinstance(raw_arguments, dict):
                action["args"] = raw_arguments
            else:
                try:
                    parsed = json.loads(raw_arguments or "{}")
                except json.JSONDecodeError as error:
                    action["error"] = (
                        f"Error: could not parse the arguments of '{name}' as JSON ({error}). "
                        "Send the arguments as a JSON object."
                    )
                else:
                    if not isinstance(parsed, dict):
                        action["error"] = f"Error: the arguments of '{name}' must be a JSON object."
                    else:
                        action["args"] = parsed
            planned.append(action)
        return planned

    def execute(self, actions: list[dict]) -> list[dict]:
        """Run the actions and return observation messages in input order."""
        if not actions:
            return []
        ctx = self.ctx_factory()
        prepared = [self._prepare(action, ctx) for action in actions]
        if any(action["tool"] in SEQUENTIAL_TOOLS for action in prepared) or len(prepared) == 1:
            return [self._run(action, ctx) for action in prepared]
        with ThreadPoolExecutor(max_workers=len(prepared)) as pool:
            return list(pool.map(lambda action: self._run(action, ctx), prepared))

    def _prepare(self, action: dict, ctx: ToolContext) -> dict:
        """Resolve permissions before running anything."""
        if action.get("error"):
            return action
        tool = self.registry.get(action["tool"])
        if tool is None:
            action["error"] = (
                f"Error: unknown tool '{action['tool']}'. Available tools: {', '.join(self.registry.names())}."
            )
            return action
        if self.hooks:
            hook = self.hooks.apply("PreToolUse", {"tool": action["tool"], "params": action["args"]})
            if hook.blocked:
                action["error"] = f"Error: the hook blocked '{action['tool']}'. {hook.reason}".strip()
                return action
            if isinstance(hook.updated_input, dict):
                """Only the arguments of a tool are a mapping. A prompt is not."""
                action["args"] = hook.updated_input
        decision = self.policy.evaluate(action["tool"], action["args"])
        action["decision"] = decision
        if decision.decision == "deny":
            action["error"] = f"Error: permission denied for '{action['tool']}'. {decision.reason}".strip()
            return action
        if decision.decision == "ask":
            approver = self.approver
            if approver is None:
                action["error"] = (
                    f"Error: '{action['tool']}' needs approval but no approver is available. "
                    "Run with --permission-mode bypass to allow it."
                )
                return action
            answer = self._ask(action, ctx, approver, decision.reason)
            if answer == ApprovalDecision.DENY:
                action["error"] = f"Error: the user denied '{action['tool']}'."
                return action
            if answer == ApprovalDecision.ALWAYS:
                self._remember(action["tool"], action["args"])
        return action

    def _ask(self, action: dict, ctx: ToolContext, approver: Approver, reason: str) -> ApprovalDecision:
        """Ask a human. The session waits for the answer.

        The request itself is published by the approver, which is the one that
        talks to the interface. The executor only says what the session is doing.
        """
        self._state(ctx, SessionState.AWAITING_APPROVAL)
        answer = approver.request(action["tool"], action["args"], reason)
        self._state(ctx, SessionState.EXECUTING)
        return answer

    def _remember(self, tool: str, params: dict) -> None:
        """Persist an 'always allow' decision in the user rule file."""
        from coderagent.tools.rules import add_rule

        add_rule(tool, pattern_for(tool, params), "allow", "always allowed by the user", self.rules_home)

    def _run(self, action: dict, ctx: ToolContext) -> dict:
        if action.get("error"):
            return self._observation(action["tool_call_id"], action["error"])
        tool = self.registry.get(action["tool"])
        path = action["args"].get("path")
        if path and self.on_path:
            self.on_path(str(path))
        if action["tool"] in WRITE_TOOLS and self.before_write:
            self.before_write(action["tool"], action["args"])
        try:
            result: ToolResult = tool.run(action["args"], ctx)
        except Exception as e:
            return self._observation(
                action["tool_call_id"], f"Error: '{action['tool']}' failed: {type(e).__name__}: {e}"
            )
        self._publish(action, result, ctx)
        if result.metadata.get("truncated"):
            ctx.session.metadata.setdefault("truncated_outputs", []).append(result.metadata["truncated"])
        content = result.content
        if self.hooks:
            hook = self.hooks.apply(
                "PostToolUse", {"tool": action["tool"], "params": action["args"], "result": content}
            )
            if hook.blocked:
                content = f"Error: the hook blocked '{action['tool']}'. {hook.reason}".strip()
            if hook.additional_context:
                content = f"{content}\n\n[hook] {hook.additional_context}"
        return self._observation(action["tool_call_id"], content)

    def _observation(self, tool_call_id: str, content: str) -> dict:
        return {"role": "tool", "tool_call_id": tool_call_id, "content": content}

    def _publish(self, action: dict, result: ToolResult, ctx: ToolContext) -> None:
        event = Event(
            type=EventType.TOOL_RESULT,
            session_id=ctx.session.id,
            timestamp=time.time(),
            payload={
                "tool": action["tool"],
                "tool_call_id": action["tool_call_id"],
                "content": result.content,
                "is_error": result.is_error,
                "diff": result.metadata.get("diff", ""),
            },
        )
        ctx.bus.publish(event)
        if self.store is not None:
            """The log keeps the result, so that the replay shows the diff of the change."""
            self.store.append(ctx.session.id, event)

    def _state(self, ctx: ToolContext, state: SessionState) -> None:
        """The state of the session follows what the agent is doing."""
        ctx.session.state = state
        self._log(ctx, EventType.STATE_CHANGE, {"state": state.value})

    def _log(self, ctx: ToolContext, event_type: EventType, payload: dict) -> None:
        """Put an event in the log of the session."""
        event = Event(type=event_type, session_id=ctx.session.id, timestamp=time.time(), payload=payload)
        ctx.bus.publish(event)
        if self.store is not None:
            self.store.append(ctx.session.id, event)
