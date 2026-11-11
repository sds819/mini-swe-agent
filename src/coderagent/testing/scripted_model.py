"""A model that replays pre-written responses, so tests never hit a real API."""

from collections.abc import Callable
from typing import Any

from coderagent.models.streaming import ModelEvent


class ScriptedModel:
    model_name = "scripted"

    def __init__(
        self,
        responses: list[dict] | None = None,
        side_effect: Callable[[list[dict]], dict] | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.side_effect = side_effect
        self.calls: list[list[dict]] = []

    def query(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> dict:
        self.calls.append(list(messages))
        if self.side_effect is not None:
            return self.side_effect(messages)
        if not self.responses:
            msg = f"ScriptedModel ran out of responses after {len(self.calls)} calls"
            raise AssertionError(msg)
        return self.responses.pop(0)

    def query_stream(self, messages: list[dict], tools: list[dict] | None = None, **kwargs):
        message = self.query(messages, tools=tools, **kwargs)
        if message.get("content"):
            yield ModelEvent(type="text", content=message["content"])
        for call in message.get("tool_calls") or []:
            yield ModelEvent(type="tool_call_done", tool_call=call)
        extra = message.get("extra") or {}
        yield ModelEvent(
            type="usage",
            cost=extra.get("cost", 0.0),
            raw={
                "usage": {
                    "prompt_tokens": extra.get("tokens_in", 0),
                    "completion_tokens": extra.get("tokens_out", 0),
                }
            },
        )

    def get_template_vars(self) -> dict[str, Any]:
        return {"model_name": "scripted"}
