"""A long session must never blow the context budget."""

from coderagent.config.schema import ContextConfig
from coderagent.core.context import ContextEngine
from coderagent.core.events import EventBus
from coderagent.core.session import SessionStore


class FakeModel:
    """Summarizes without calling a real model."""

    def complete(self, messages, **kwargs) -> str:
        return '{"goal": "keep going", "findings": [], "decisions": [], "files_touched": [], "open_questions": [], "next_steps": [], "errors_seen": []}'

    def query(self, messages, tools=None, **kwargs) -> dict:
        return {"role": "assistant", "content": "ok"}


def test_two_hundred_turns_never_exceed_the_budget(tmp_path):
    config = ContextConfig(context_window=4000, reserved_output=500, compact_threshold=0.8, keep_recent_turns=5)
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    engine = ContextEngine(session, store, EventBus(), config, FakeModel(), cwd=tmp_path, user_home=tmp_path / "home")

    seen = []
    for index in range(200):
        engine.append({"role": "user", "content": f"question {index} " + "x" * 200})
        engine.append({"role": "assistant", "content": f"answer {index} " + "y" * 400})
        session.turn_count += 1
        engine.maybe_compact()
        seen.append(engine.estimated_tokens())

    assert max(seen) <= config.context_window - config.reserved_output
    assert engine.summary is not None
    assert len(engine.history.messages) < 200


def test_the_context_shrinks_after_a_compaction(tmp_path):
    config = ContextConfig(context_window=4000, reserved_output=500, keep_recent_turns=5)
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    engine = ContextEngine(session, store, EventBus(), config, FakeModel(), cwd=tmp_path, user_home=tmp_path / "home")
    for index in range(50):
        engine.append({"role": "user", "content": f"question {index} " + "x" * 200})
        engine.append({"role": "assistant", "content": f"answer {index} " + "y" * 400})
    before = engine.estimated_tokens()
    assert engine.compact()
    assert engine.estimated_tokens() < before


def test_the_summary_holds_the_state_of_the_compacted_part(tmp_path):
    config = ContextConfig(context_window=4000, reserved_output=500, keep_recent_turns=5)
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    engine = ContextEngine(session, store, EventBus(), config, FakeModel(), cwd=tmp_path, user_home=tmp_path / "home")
    for index in range(50):
        engine.append({"role": "user", "content": f"question {index}"})
        engine.append({"role": "assistant", "content": f"answer {index}"})
    engine.compact()
    text = engine.build_messages()[0]["content"]
    assert "<session_summary>" in text
    assert "keep going" in text
