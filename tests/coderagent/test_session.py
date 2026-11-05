import time

from coderagent.core.events import Event, EventType
from coderagent.core.session import Session, SessionState, SessionStore


def test_rebuild_matches_appended_events(tmp_path):
    store = SessionStore(tmp_path)
    session = store.create(tmp_path)
    store.append(session.id, Event(EventType.USER_MESSAGE, session.id, 2.0, {"content": "fix the bug"}))
    store.append(
        session.id,
        Event(EventType.ASSISTANT_MESSAGE, session.id, 3.0, {"message": {"role": "assistant"}, "cost": 0.25}),
    )
    store.append(session.id, Event(EventType.STATE_CHANGE, session.id, 4.0, {"state": "thinking"}))
    store.append(session.id, Event(EventType.TOOL_RESULT, session.id, 5.0, {"messages": []}))

    rebuilt = store.rebuild(session.id)
    assert rebuilt == Session(
        id=session.id,
        cwd=tmp_path,
        created_at=session.created_at,
        updated_at=5.0,
        state=SessionState.THINKING,
        turn_count=1,
        total_cost=0.25,
    )


def test_rebuild_skips_unknown_event_types(tmp_path):
    store = SessionStore(tmp_path)
    session = store.create(tmp_path)
    with store.path(session.id).open("a", encoding="utf-8") as f:
        f.write('{"type": "future_event", "session_id": "x", "timestamp": 9.0, "payload": {}}\n')
    assert len(store.events(session.id)) == 1
    assert store.rebuild(session.id).state == SessionState.IDLE


def test_list_is_newest_first(tmp_path):
    store = SessionStore(tmp_path)
    older = store.create(tmp_path)
    newer = store.create(tmp_path)
    store.append(older.id, Event(EventType.STATE_CHANGE, older.id, 0.0, {"state": "idle", "created_at": 100.0}))
    store.append(newer.id, Event(EventType.STATE_CHANGE, newer.id, 0.0, {"state": "idle", "created_at": 200.0}))
    assert [s.id for s in store.list()] == [newer.id, older.id]


def test_list_filters_by_cwd(tmp_path):
    store = SessionStore(tmp_path)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    in_a = store.create(tmp_path / "a")
    store.create(tmp_path / "b")
    assert [s.id for s in store.list(cwd=tmp_path / "a")] == [in_a.id]
    assert len(store.list()) == 2


def test_session_id_and_files(tmp_path):
    store = SessionStore(tmp_path)
    session = store.create(tmp_path)
    assert store.path(session.id) == tmp_path / f"{session.id}.jsonl"
    assert store.meta_path(session.id).exists()
    assert session.id.startswith(time.strftime("%Y%m%d"))
