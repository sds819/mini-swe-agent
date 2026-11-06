"""The commands the user can trigger."""

from coderagent.config.schema import ContextConfig
from coderagent.core.context import ContextEngine
from coderagent.core.events import EventBus, EventType
from coderagent.core.session import SessionStore
from coderagent.ui.commands.compact import compact


def _context(tmp_path, turns: int = 30) -> ContextEngine:
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    context = ContextEngine(
        session,
        store,
        EventBus(),
        ContextConfig(keep_recent_turns=5),
        None,
        cwd=tmp_path,
        user_home=tmp_path / "home",
    )
    for index in range(turns):
        context.append({"role": "user", "content": f"question {index}"})
        context.append({"role": "assistant", "content": f"answer {index}"})
    return context


def test_the_compact_command_shrinks_the_context(tmp_path):
    context = _context(tmp_path)
    before = len(context.history.messages)
    assert compact(context)
    assert len(context.history.messages) < before
    assert context.summary is not None


def test_the_compact_command_publishes_an_event(tmp_path):
    context = _context(tmp_path)
    events = []
    context.bus.subscribe(EventType.COMPACTION, events.append)
    assert compact(context)
    assert len(events) == 1
    assert events[0].payload["compacted_messages"] > 0


def test_the_compact_command_does_nothing_when_there_is_nothing_to_compact(tmp_path):
    context = _context(tmp_path, turns=2)
    assert compact(context) is False
    assert context.summary is None
