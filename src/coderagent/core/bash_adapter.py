"""Adapter running the M0 bash tool through mini-swe-agent's local environment."""

import json

from minisweagent.environments.local import LocalEnvironment
from minisweagent.exceptions import FormatError
from minisweagent.models.utils.actions_toolcall import format_toolcall_observation_messages

OBSERVATION_TEMPLATE = (
    "{% if output.exception_info %}<exception>{{output.exception_info}}</exception>\n{% endif %}"
    "<returncode>{{output.returncode}}</returncode>\n<output>\n{{output.output}}</output>"
)


class BashExecutor:
    """M0 stand-in for the real tool registry: a single bash tool."""

    def __init__(self, env=None, *, cwd: str = "", timeout: int = 120) -> None:
        self.env = env if env is not None else LocalEnvironment(cwd=cwd, timeout=timeout)
        self.cwd = cwd

    def plan(self, tool_calls: list[dict]) -> list[dict]:
        actions = []
        for call in tool_calls:
            function = call.get("function", {})
            try:
                args = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError as e:
                raise FormatError(
                    {
                        "role": "user",
                        "content": f"Could not parse the arguments of tool call {call.get('id', '')}: {e}",
                        "extra": {"interrupt_type": "FormatError"},
                    }
                )
            actions.append(
                {
                    "tool": function.get("name", ""),
                    "tool_call_id": call.get("id", ""),
                    "args": args,
                    "raw": call,
                }
            )
        return actions

    def execute(self, actions: list[dict]) -> list[dict]:
        outputs = [self.env.execute({"command": action["args"].get("command", "")}, cwd=self.cwd) for action in actions]
        return format_toolcall_observation_messages(
            actions=actions, outputs=outputs, observation_template=OBSERVATION_TEMPLATE
        )
