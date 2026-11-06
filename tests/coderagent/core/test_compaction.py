"""Compaction replaces the older part of the history with a summary."""

from pathlib import Path

from coderagent.config.schema import ContextConfig
from coderagent.core.context import ContextEngine
from coderagent.core.events import EventBus, EventType
from coderagent.core.session import SessionStore
from coderagent.core.summarize import Summary


class FakeModel:
    def __init__(self, answer: str = '{"goal": "the goal"}') -> None:
        self.answer = answer
        self.calls = 0

    def complete(self, messages, **kwargs) -> str:
        self.calls += 1
        return self.answer


def make_engine(tmp_path: Path, model=None, **kwargs) -> ContextEngine:
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    return ContextEngine(
        session,
        store,
        EventBus(),
        kwargs.pop("config", ContextConfig()),
        model or FakeModel(),
        cwd=tmp_path,
        user_home=tmp_path / "home",
        **kwargs,
    )


def fill(engine: ContextEngine, turns: int) -> None:
    for index in range(turns):
        engine.append({"role": "user", "content": f"question {index}"})
        engine.append({"role": "assistant", "content": f"answer {index}"})


def test_compact_summarizes_the_older_turns_and_keeps_the_recent_ones(tmp_path):
    config = ContextConfig(keep_recent_turns=2, keep_recent_token_ratio=0.0)
    engine = make_engine(tmp_path, config=config)
    fill(engine, 6)
    assert engine.compact()
    assert len(engine.history.messages) == 4
    assert engine.summary is not None
    assert engine.summary.goal == "the goal"


def test_compact_cuts_on_a_turn_boundary(tmp_path):
    config = ContextConfig(keep_recent_turns=1, keep_recent_token_ratio=0.0)
    engine = make_engine(tmp_path, config=config)
    engine.append({"role": "user", "content": "q0"})
    engine.append({"role": "assistant", "content": "a0", "tool_calls": [{"id": "1", "function": {"name": "read"}}]})
    engine.append({"role": "tool", "tool_call_id": "1", "content": "content"})
    engine.append({"role": "user", "content": "q1"})
    assert engine.compact()
    assert engine.history.messages[0]["content"] == "q1"


def test_compact_of_an_empty_history_does_nothing(tmp_path):
    engine = make_engine(tmp_path)
    assert engine.compact() is False
    assert engine.summary is None


def test_compact_of_a_single_turn_does_nothing(tmp_path):
    config = ContextConfig(keep_recent_turns=5, keep_recent_token_ratio=0.0)
    engine = make_engine(tmp_path, config=config)
    fill(engine, 1)
    assert engine.compact() is False


def test_compact_publishes_an_event_that_can_be_replayed(tmp_path):
    config = ContextConfig(keep_recent_turns=2, keep_recent_token_ratio=0.0)
    engine = make_engine(tmp_path, config=config)
    fill(engine, 6)
    events = []
    engine.bus.subscribe(EventType.COMPACTION, events.append)
    assert engine.compact()
    assert len(events) == 1
    payload = events[0].payload
    assert payload["compacted_messages"] == 8
    assert payload["summary"]["goal"] == "the goal"


def test_restore_after_a_compaction_gives_the_same_view(tmp_path):
    config = ContextConfig(keep_recent_turns=2, keep_recent_token_ratio=0.0)
    engine = make_engine(tmp_path, config=config)
    fill(engine, 6)
    engine.compact()
    messages = engine.history.messages
    summary = engine.summary

    restored = ContextEngine(engine.session, engine.store, EventBus(), config, FakeModel(), cwd=tmp_path)
    restored.restore()
    assert restored.history.messages == messages
    assert restored.summary == summary


def test_the_summary_model_is_used_and_the_fallback_takes_over_when_it_fails(tmp_path):
    class BrokenModel:
        def complete(self, messages, **kwargs) -> str:
            raise RuntimeError("no summary for you")

    config = ContextConfig(keep_recent_turns=1, keep_recent_token_ratio=0.0)
    engine = make_engine(tmp_path, model=BrokenModel(), config=config)
    fill(engine, 4)
    assert engine.compact()
    assert engine.summary.goal == "the earlier part of the conversation was compacted"
    assert engine.summary.findings


def test_a_summary_without_the_touched_files_is_rejected(tmp_path):
    class EmptyModel:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, messages, **kwargs) -> str:
            self.calls += 1
            return '{"goal": "g", "files_touched": []}'

    model = EmptyModel()
    config = ContextConfig(keep_recent_turns=1, keep_recent_token_ratio=0.0)
    engine = make_engine(tmp_path, model=model, config=config)
    engine.append({"role": "user", "content": "fix it"})
    engine.append(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "1", "function": {"name": "edit", "arguments": '{"path": "a.py"}'}}],
        }
    )
    engine.append({"role": "user", "content": "and now"})
    assert engine.compact()
    assert model.calls == 2
    assert engine.summary.goal != "g"


def test_maybe_compact_triggers_on_the_budget(tmp_path):
    config = ContextConfig(context_window=100, reserved_output=0, compact_threshold=0.5, keep_recent_turns=1)
    engine = make_engine(tmp_path, config=config)
    fill(engine, 20)
    assert engine.maybe_compact()
    assert engine.summary is not None


def test_maybe_compact_does_nothing_when_the_budget_is_far_away(tmp_path):
    config = ContextConfig(context_window=100000, auto_compact=True)
    engine = make_engine(tmp_path, config=config)
    fill(engine, 3)
    assert engine.maybe_compact() is False
    assert engine.summary is None


def test_maybe_compact_can_be_switched_off(tmp_path):
    config = ContextConfig(context_window=100, reserved_output=0, compact_threshold=0.5, auto_compact=False)
    engine = make_engine(tmp_path, config=config)
    fill(engine, 20)
    assert engine.maybe_compact() is False


def test_maybe_compact_triggers_on_the_turn_count(tmp_path):
    config = ContextConfig(context_window=1000000, compact_every_turns=3, keep_recent_turns=1)
    engine = make_engine(tmp_path, config=config)
    fill(engine, 4)
    engine.session.turn_count = 4
    assert engine.maybe_compact()


def test_the_recent_errors_survive_the_compaction(tmp_path):
    config = ContextConfig(keep_recent_turns=1, keep_recent_token_ratio=0.0)
    engine = make_engine(tmp_path, config=config)
    engine.append({"role": "user", "content": "q0"})
    engine.append({"role": "tool", "tool_call_id": "1", "content": "Error: the file was not found"})
    engine.append({"role": "user", "content": "q1"})
    assert engine.compact()
    assert engine.summary.recent_errors == ["Error: the file was not found"]
    assert "the file was not found" in engine.summary.render()


def test_the_summary_survives_a_round_trip_through_the_events(tmp_path):
    config = ContextConfig(keep_recent_turns=1, keep_recent_token_ratio=0.0)
    engine = make_engine(tmp_path, config=config)
    fill(engine, 4)
    engine.compact()
    restored = ContextEngine(engine.session, engine.store, EventBus(), config, FakeModel(), cwd=tmp_path)
    restored.restore()
    assert isinstance(restored.summary, Summary)
    assert restored.summary.goal == "the goal"


def test_the_cost_of_the_summary_is_recorded_and_booked(tmp_path):
    """The summary is a model call, so it costs money and the session knows it."""

    class CostlyModel(FakeModel):
        def __init__(self) -> None:
            super().__init__()
            self.total_cost = 0.0

        def complete(self, messages, **kwargs) -> str:
            self.total_cost += 0.05
            return super().complete(messages, **kwargs)

    model = CostlyModel()
    config = ContextConfig(keep_recent_turns=1, keep_recent_token_ratio=0.0)
    engine = make_engine(tmp_path, model=model, config=config)
    fill(engine, 4)
    assert engine.compact()
    events = engine.store.events(engine.session.id)
    assert [event.payload["cost"] for event in events if event.type == EventType.COMPACTION] == [0.05]
