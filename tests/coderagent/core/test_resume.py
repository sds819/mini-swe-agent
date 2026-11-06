"""Sessions can be continued, forked and listed."""

from coderagent.core.events import Event, EventBus, EventType
from coderagent.core.session import SessionStore
from coderagent.ui.cli import pick_session, render_sessions
from coderagent.ui.commands.resume import fork, latest_session, list_sessions, resume


def _store(tmp_path) -> SessionStore:
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    store.append(
        session.id,
        Event(
            type=EventType.USER_MESSAGE,
            session_id=session.id,
            timestamp=1.0,
            payload={"content": "hello"},
        ),
    )
    return store


def test_the_sessions_of_a_directory_are_listed_newest_first(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    first = store.create(tmp_path)
    second = store.create(tmp_path)
    assert [session.id for session in list_sessions(store, tmp_path)] == [second.id, first.id]


def test_the_sessions_of_another_directory_are_not_listed(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    store.create(tmp_path / "other")
    assert list_sessions(store, tmp_path) == []


def test_the_latest_session_is_the_one_that_was_worked_on_last(tmp_path):
    store = _store(tmp_path)
    assert latest_session(store, tmp_path).id == store.list(tmp_path)[0].id


def test_resuming_rebuilds_the_session(tmp_path):
    store = _store(tmp_path)
    session = store.list(tmp_path)[0]
    assert resume(store, session.id).turn_count == 1


def test_forking_copies_the_session_and_leaves_the_original_alone(tmp_path):
    store = _store(tmp_path)
    original = store.list(tmp_path)[0]
    forked = fork(store, original.id)

    assert forked.id != original.id
    assert forked.turn_count == 1
    assert [event.type for event in store.events(forked.id)] == [
        *[event.type for event in store.events(original.id)],
        EventType.STATE_CHANGE,
    ]
    assert all(event.session_id == forked.id for event in store.events(forked.id))


def test_the_fork_continues_on_its_own(tmp_path):
    store = _store(tmp_path)
    original = store.list(tmp_path)[0]
    forked = fork(store, original.id)
    store.append(
        forked.id,
        Event(
            type=EventType.USER_MESSAGE,
            session_id=forked.id,
            timestamp=2.0,
            payload={"content": "only in the fork"},
        ),
    )
    assert store.rebuild(forked.id).turn_count == 2
    assert store.rebuild(original.id).turn_count == 1


def test_the_cli_picks_the_session_to_continue(tmp_path):
    store = _store(tmp_path)
    session = store.list(tmp_path)[0]
    assert pick_session(store, tmp_path, resume=session.id).id == session.id
    assert pick_session(store, tmp_path, continue_last=True).id == session.id
    assert pick_session(store, tmp_path, fork=session.id).id != session.id
    assert pick_session(store, tmp_path) is None


def test_the_session_list_is_rendered(tmp_path):
    store = _store(tmp_path)
    rendered = render_sessions(list_sessions(store, tmp_path))
    assert store.list(tmp_path)[0].id in rendered
    assert "1 turns" in rendered
    assert "no sessions yet" == render_sessions([])


def test_the_session_list_can_be_rendered_as_json(tmp_path):
    import json

    store = _store(tmp_path)
    data = json.loads(render_sessions(list_sessions(store, tmp_path), "json"))
    assert data[0]["turns"] == 1
    assert data[0]["cwd"] == str(tmp_path)


def test_a_resumed_session_continues_the_conversation(tmp_path):
    from coderagent.core.loop import AgentLoop
    from coderagent.models.gateway import ModelGateway
    from coderagent.testing.factory import build_executor
    from coderagent.testing.scripted_model import ScriptedModel

    store = _store(tmp_path)
    session = store.list(tmp_path)[0]
    executor = build_executor(tmp_path)
    loop = AgentLoop(
        ModelGateway(ScriptedModel([{"role": "assistant", "content": "still here", "extra": {"cost": 0.0}}])),
        executor,
        session,
        store,
        EventBus(),
        tools=executor.registry.schemas(),
    )
    assert [message["content"] for message in loop.messages] == ["hello"]
    result = loop.run_turn("and now?")
    assert result.stop_reason == "end_turn"
    assert store.rebuild(session.id).turn_count == 2
