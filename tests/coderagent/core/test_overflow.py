"""The context overflow fallback: the provider says the context is too big, we compact and resend."""

import litellm

from coderagent.core.events import EventBus
from coderagent.core.loop import AgentLoop
from coderagent.core.session import SessionStore
from coderagent.models.gateway import ModelGateway, is_context_overflow
from coderagent.testing.factory import build_executor


class OverflowingModel:
    """Fails with a context overflow until `fail_times` is reached."""

    def __init__(self, fail_times: int = 1, content: str = "done") -> None:
        self.fail_times = fail_times
        self.content = content
        self.summary = (
            '{"goal": "the old goal", "findings": [], "decisions": [], "files_touched": [], '
            '"open_questions": [], "next_steps": [], "errors_seen": []}'
        )
        self.calls = 0
        self.seen: list[list[dict]] = []

    def query(self, messages, tools=None, **kwargs) -> dict:
        if tools is None:
            # The summarizer asks for a summary, that never overflows.
            return {"role": "assistant", "content": self.summary}
        self.calls += 1
        self.seen.append(messages)
        if self.calls <= self.fail_times:
            raise litellm.exceptions.ContextWindowExceededError(
                message="This model's maximum context length is 8192 tokens",
                model="test-model",
                llm_provider="openai",
            )
        return {"role": "assistant", "content": self.content}


def _loop(tmp_path, model, **kwargs):
    store = SessionStore(tmp_path)
    session = store.create(tmp_path)
    executor = build_executor(tmp_path)
    loop = AgentLoop(
        ModelGateway(model),
        executor,
        session,
        store,
        EventBus(),
        tools=executor.registry.schemas(),
        **kwargs,
    )
    return loop, store, session


def _overflow() -> Exception:
    return litellm.exceptions.ContextWindowExceededError(
        message="maximum context length is 8192 tokens", model="test-model", llm_provider="openai"
    )


def test_is_context_overflow_knows_the_provider_errors():
    assert is_context_overflow(_overflow()) is True
    assert is_context_overflow(RuntimeError("context window exceeded")) is True
    assert is_context_overflow(RuntimeError("context_length_exceeded")) is True
    assert is_context_overflow(RuntimeError("maximum context length reached")) is True
    assert is_context_overflow(RuntimeError("the model is on fire")) is False


def _prefill(loop, turns: int = 25) -> None:
    """A history that is long enough to be compacted."""
    for index in range(turns):
        loop.context.append({"role": "user", "content": f"question {index}"})
        loop.context.append({"role": "assistant", "content": f"answer {index}"})


def test_the_turn_survives_an_overflow(tmp_path):
    model = OverflowingModel()
    loop, store, session = _loop(tmp_path, model)
    _prefill(loop)
    result = loop.run_turn("hello")
    assert result.stop_reason == "end_turn"
    assert model.calls == 2
    assert result.messages[-1]["content"] == "done"


def test_the_context_is_compacted_before_the_second_attempt(tmp_path):
    model = OverflowingModel()
    loop, _, _ = _loop(tmp_path, model)
    _prefill(loop)
    loop.run_turn("hello")
    assert len(model.seen[1]) < len(model.seen[0])
    assert any("<session_summary>" in str(message.get("content", "")) for message in model.seen[1])


def test_a_second_overflow_stops_the_turn(tmp_path):
    model = OverflowingModel(fail_times=2)
    loop, store, session = _loop(tmp_path, model)
    _prefill(loop)
    result = loop.run_turn("hello")
    assert result.stop_reason == "error"
    assert "ContextWindowExceededError" in result.error


def test_an_overflow_with_nothing_to_compact_stops_the_turn(tmp_path):
    class AlwaysOverflowing:
        def query(self, messages, tools=None, **kwargs) -> dict:
            raise _overflow()

    loop, _, _ = _loop(tmp_path, AlwaysOverflowing())
    result = loop.run_turn("hello")
    assert result.stop_reason == "error"
    assert "nothing left to compact" in result.error


def test_a_normal_error_is_not_treated_as_an_overflow(tmp_path):
    class BrokenModel:
        def query(self, messages, tools=None, **kwargs) -> dict:
            raise RuntimeError("the model is on fire")

    loop, _, _ = _loop(tmp_path, BrokenModel())
    result = loop.run_turn("hello")
    assert result.stop_reason == "error"
    assert "the model is on fire" in result.error
