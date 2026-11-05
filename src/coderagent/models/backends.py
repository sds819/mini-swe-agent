"""Model backends. Reuses mini-swe-agent's retry and cache-control primitives."""

import logging
from collections.abc import Iterator
from typing import Any

import litellm

from minisweagent.models.utils.cache_control import set_cache_control
from minisweagent.models.utils.retry import retry

logger = logging.getLogger("coderagent.backend")


class LiteLLMBackend:
    """Calls `litellm.completion` and normalizes the response."""

    abort_exceptions: list[type[Exception]] = [
        litellm.exceptions.UnsupportedParamsError,
        litellm.exceptions.NotFoundError,
        litellm.exceptions.PermissionDeniedError,
        litellm.exceptions.ContextWindowExceededError,
        litellm.exceptions.AuthenticationError,
        litellm.exceptions.BadRequestError,
        KeyboardInterrupt,
    ]

    def __init__(
        self,
        model_name: str,
        *,
        model_kwargs: dict[str, Any] | None = None,
        set_cache_control: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.model_kwargs = model_kwargs or {}
        self.set_cache_control = set_cache_control

    def query(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> dict:
        prepared = set_cache_control(
            [{k: v for k, v in message.items() if k != "extra"} for message in messages],
            mode=self.set_cache_control,
        )
        call_kwargs = self.model_kwargs | kwargs
        if tools:
            call_kwargs["tools"] = tools
        for attempt in retry(logger=logger, abort_exceptions=self.abort_exceptions):
            with attempt:
                response = litellm.completion(model=self.model_name, messages=prepared, **call_kwargs)
        return self._normalize(response)

    def query_stream(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> Iterator[dict]:
        """Real streaming arrives in M3; until then this yields the complete message once."""
        yield self.query(messages, tools=tools, **kwargs)

    def get_template_vars(self) -> dict[str, Any]:
        return {"model_name": self.model_name, **self.model_kwargs}

    def _normalize(self, response) -> dict:
        message = response.choices[0].message.model_dump()
        return {
            "role": "assistant",
            "content": message.get("content") or "",
            "tool_calls": message.get("tool_calls") or [],
            "extra": {"cost": self._cost(response)},
        }

    def _cost(self, response) -> float:
        try:
            return float(litellm.cost_calculator.completion_cost(response, model=self.model_name))
        except Exception as e:
            logger.warning("Could not calculate cost for model %s: %s", self.model_name, e)
            return 0.0
