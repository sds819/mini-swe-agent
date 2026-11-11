"""Model backends and the gateway that fronts them."""

from collections.abc import Iterator
from typing import Any

import litellm

from coderagent.core.protocols import ModelBackend
from coderagent.models.streaming import ModelEvent, message_from_events, usage_tokens


def is_context_overflow(error: Exception) -> bool:
    """True when the provider refused the request because the context was too long."""
    if isinstance(error, litellm.exceptions.ContextWindowExceededError):
        return True
    text = str(error).lower()
    return any(marker in text for marker in ("context window", "context_length_exceeded", "maximum context length"))


class ModelGateway:
    """Fronts one or more model backends and keeps track of what they spend."""

    def __init__(self, backend: ModelBackend) -> None:
        self.backend = backend
        self.total_cost = 0.0
        self.total_tokens_in = 0
        self.total_tokens_out = 0
        """The tokens of every call. The budget of a model that has no price."""
        self.n_calls = 0

    @property
    def total_tokens(self) -> int:
        """The tokens of every call, in and out."""
        return self.total_tokens_in + self.total_tokens_out

    def query_stream(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> Iterator[ModelEvent]:
        """The answer as it arrives. The cost is booked when the provider reports it."""
        self.n_calls += 1
        for event in self.backend.query_stream(messages, tools=tools, **kwargs):
            if event.type == "usage":
                self.total_cost += event.cost
                prompt, completion = usage_tokens(event.raw.get("usage"))
                self.total_tokens_in += prompt
                self.total_tokens_out += completion
            yield event

    def query(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> dict:
        """The whole answer in one piece."""
        return message_from_events(self.query_stream(messages, tools=tools, **kwargs))

    def complete(self, messages: list[dict], **kwargs) -> str:
        """Non-streaming convenience call, e.g. for summarization."""
        return self.query(messages, **kwargs).get("content", "")

    def get_template_vars(self) -> dict[str, Any]:
        return self.backend.get_template_vars()
