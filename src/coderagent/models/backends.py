"""Model backends. Reuses mini-swe-agent's retry and cache-control primitives."""

import logging
from collections.abc import Iterator
from typing import Any

import litellm

from coderagent.models.streaming import ModelEvent, ToolCallAccumulator, message_from_events
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
        return message_from_events(self.query_stream(messages, tools=tools, **kwargs))

    def query_stream(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> Iterator[ModelEvent]:
        """The answer as it arrives: text, reasoning and tool call fragments."""
        prepared = set_cache_control(
            [{k: v for k, v in message.items() if k != "extra"} for message in messages],
            mode=self.set_cache_control,
        )
        call_kwargs = self.model_kwargs | kwargs
        if tools:
            call_kwargs["tools"] = tools
        call_kwargs["stream"] = True
        call_kwargs.setdefault("stream_options", {"include_usage": True})
        yield from self._events(self._open_stream(prepared, call_kwargs))

    def get_template_vars(self) -> dict[str, Any]:
        return {"model_name": self.model_name, **self.model_kwargs}

    def _open_stream(self, messages: list[dict], call_kwargs: dict):
        for attempt in retry(logger=logger, abort_exceptions=self.abort_exceptions):
            with attempt:
                return litellm.completion(model=self.model_name, messages=messages, **call_kwargs)
        raise RuntimeError("the retry loop ended without a response")

    def _events(self, response) -> Iterator[ModelEvent]:
        accumulator = ToolCallAccumulator()
        for chunk in response:
            delta = self._delta(chunk)
            if delta is not None:
                reasoning = self._field(delta, "reasoning_content") or self._field(delta, "reasoning")
                if reasoning:
                    yield ModelEvent(type="reasoning", content=reasoning)
                text = self._field(delta, "content")
                if text:
                    yield ModelEvent(type="text", content=text)
                for fragment in self._tool_call_fragments(delta):
                    accumulator.feed(fragment)
                    yield ModelEvent(type="tool_call_delta", raw=fragment)
            usage = self._field(chunk, "usage")
            if usage:
                yield ModelEvent(type="usage", cost=self._stream_cost(usage), raw={"usage": usage})
        for call in accumulator.finish():
            yield ModelEvent(type="tool_call_done", tool_call=call)

    @staticmethod
    def _delta(chunk) -> Any:
        choices = getattr(chunk, "choices", None) or []
        return getattr(choices[0], "delta", None) if choices else None

    @staticmethod
    def _field(obj, name: str):
        value = getattr(obj, name, None)
        if value is None and isinstance(obj, dict):
            value = obj.get(name)
        return value

    @staticmethod
    def _tool_call_fragments(delta) -> list[dict]:
        fragments = []
        for call in getattr(delta, "tool_calls", None) or []:
            if isinstance(call, dict):
                fragments.append(call)
            elif hasattr(call, "model_dump"):
                fragments.append(call.model_dump())
            else:  # pragma: no cover - providers always give one of the two
                function = getattr(call, "function", None)
                fragments.append(
                    {
                        "index": getattr(call, "index", 0),
                        "id": getattr(call, "id", "") or "",
                        "function": {
                            "name": getattr(function, "name", "") or "",
                            "arguments": getattr(function, "arguments", "") or "",
                        },
                    }
                )
        return fragments

    def _stream_cost(self, usage) -> float:
        prompt = int(self._field(usage, "prompt_tokens") or 0)
        completion = int(self._field(usage, "completion_tokens") or 0)
        try:
            prompt_cost, completion_cost = litellm.cost_calculator.cost_per_token(
                model=self.model_name, prompt_tokens=prompt, completion_tokens=completion
            )
            return float(prompt_cost) + float(completion_cost)
        except Exception as e:
            logger.warning("Could not calculate cost for model %s: %s", self.model_name, e)
            return 0.0
