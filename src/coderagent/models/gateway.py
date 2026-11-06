"""Model backends and the gateway that fronts them."""

from collections.abc import Iterator
from typing import Any

import litellm

from coderagent.core.protocols import ModelBackend
from coderagent.models.streaming import ModelEvent, message_from_events


def is_context_overflow(error: Exception) -> bool:
    """True when the provider refused the request because the context was too long."""
    if isinstance(error, litellm.exceptions.ContextWindowExceededError):
        return True
    text = str(error).lower()
    return any(marker in text for marker in ("context window", "context_length_exceeded", "maximum context length"))


class ModelGateway:
    """Fronts one or more model backends and keeps track of the money spent."""

    def __init__(self, backend: ModelBackend) -> None:
        self.backend = backend
        self.total_cost = 0.0
        self.n_calls = 0

    def query_stream(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> Iterator[ModelEvent]:
        """The answer as it arrives. The cost is booked when the provider reports it."""
        self.n_calls += 1
        for event in self.backend.query_stream(messages, tools=tools, **kwargs):
            if event.type == "usage":
                self.total_cost += event.cost
            yield event

    def query(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> dict:
        """The whole answer in one piece."""
        return message_from_events(self.query_stream(messages, tools=tools, **kwargs))

    def complete(self, messages: list[dict], **kwargs) -> str:
        """Non-streaming convenience call, e.g. for summarization."""
        return self.query(messages, **kwargs).get("content", "")

    def get_template_vars(self) -> dict[str, Any]:
        return self.backend.get_template_vars()
