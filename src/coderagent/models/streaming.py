"""Streaming model events.

A streamed answer arrives in pieces: text, reasoning and the fragments of a tool
call. `ModelEvent` is the common currency between the backends and the UI, and
`message_from_events` folds the pieces back into one assistant message.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from minisweagent.exceptions import FormatError


@dataclass
class ModelEvent:
    type: str
    """One of `text`, `reasoning`, `tool_call_delta`, `tool_call_done`, `usage`, `error`."""
    content: str = ""
    tool_call: dict | None = None
    cost: float = 0.0
    raw: dict = field(default_factory=dict)


def _format_error(message: str) -> FormatError:
    """minisweagent's FormatError keeps the details in `messages`, not in the text."""
    error = FormatError({"error": message})
    error.args = (message,)
    return error


class ToolCallAccumulator:
    """Collects the pieces of the tool calls that arrive in pieces.

    Providers differ: some send the function name once, some repeat it in every
    fragment, some split it. The arguments always arrive as JSON fragments.
    """

    def __init__(self) -> None:
        self._calls: dict[int, dict] = {}

    def feed(self, delta: dict) -> None:
        index = delta.get("index", 0)
        call = self._calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
        if delta.get("id"):
            call["id"] = delta["id"]
        function = delta.get("function") or {}
        call["name"] = self._merge_name(call["name"], function.get("name") or "")
        call["arguments"] += function.get("arguments") or ""

    @staticmethod
    def _merge_name(current: str, fragment: str) -> str:
        """Add a name fragment, without repeating what we already have."""
        if not fragment or fragment == current:
            return current
        if not current:
            return fragment
        if fragment.startswith(current):
            return fragment
        if current.startswith(fragment):
            return current
        return current + fragment

    def finish(self) -> list[dict]:
        """The parsed tool calls. Raises FormatError when the arguments are not JSON."""
        calls = []
        for index in sorted(self._calls):
            call = self._calls[index]
            try:
                json.loads(call["arguments"] or "{}")
            except json.JSONDecodeError as error:
                raise _format_error(f"could not parse the arguments of '{call['name']}' as JSON: {error}") from error
            calls.append(
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {"name": call["name"], "arguments": call["arguments"] or "{}"},
                }
            )
        return calls


def message_from_events(events) -> dict:
    """Fold a stream of events back into one assistant message."""
    content: list[str] = []
    reasoning: list[str] = []
    tool_calls: list[dict] = []
    cost = 0.0
    tokens_in = 0
    tokens_out = 0
    for event in events:
        if event.type == "text":
            content.append(event.content)
        elif event.type == "reasoning":
            reasoning.append(event.content)
        elif event.type == "tool_call_done" and event.tool_call:
            tool_calls.append(event.tool_call)
        elif event.type == "usage":
            cost += event.cost
            prompt, completion = _tokens(event.raw.get("usage"))
            tokens_in += prompt
            tokens_out += completion
    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(content),
        "extra": {"cost": cost, "tokens_in": tokens_in, "tokens_out": tokens_out},
    }
    if reasoning:
        message["extra"]["reasoning"] = "".join(reasoning)
    # An empty tool_calls array is rejected by some providers, so it is left out.
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message


def _tokens(usage) -> tuple[int, int]:
    """The tokens of a usage object, which is a dict or a model."""
    if usage is None:
        return 0, 0
    if isinstance(usage, dict):
        return int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    return int(getattr(usage, "prompt_tokens", 0) or 0), int(getattr(usage, "completion_tokens", 0) or 0)
