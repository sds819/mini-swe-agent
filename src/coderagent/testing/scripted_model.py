"""A model that replays pre-written responses, so tests never hit a real API."""

from collections.abc import Callable
from typing import Any


class ScriptedModel:
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
        yield self.query(messages, tools=tools, **kwargs)

    def get_template_vars(self) -> dict[str, Any]:
        return {"model_name": "scripted"}
