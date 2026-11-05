"""Model backends and the gateway that fronts them."""

from typing import Any

from coderagent.core.protocols import ModelBackend


class ModelGateway:
    """Fronts one or more model backends and keeps track of the money spent."""

    def __init__(self, backend: ModelBackend) -> None:
        self.backend = backend
        self.total_cost = 0.0
        self.n_calls = 0

    def query(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> dict:
        message = self.backend.query(messages, tools=tools, **kwargs)
        self.total_cost += message.get("extra", {}).get("cost", 0.0)
        self.n_calls += 1
        return message

    def complete(self, messages: list[dict], **kwargs) -> str:
        """Non-streaming convenience call, e.g. for summarization."""
        return self.query(messages, **kwargs).get("content", "")

    def get_template_vars(self) -> dict[str, Any]:
        return self.backend.get_template_vars()
