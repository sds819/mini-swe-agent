import json

from coderagent.core.events import Event, EventType
from coderagent.core.session import SessionStore


def _message(session_id: str, text: str) -> Event:
    return Event(type=EventType.USER_MESSAGE, session_id=session_id, timestamp=1.0, payload={"content": text})


def test_a_broken_line_does_not_lose_the_session(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    store.append(session.id, _message(session.id, "first"))
    with store.path(session.id).open("a", encoding="utf-8") as f:
        f.write('{"type": "user_message", "payl\n')
    store.append(session.id, _message(session.id, "second"))

    events = store.events(session.id)
    assert [event.payload.get("content") for event in events if event.type == EventType.USER_MESSAGE] == [
        "first",
        "second",
    ]
    assert store.rebuild(session.id).turn_count == 2


def test_a_broken_meta_file_does_not_lose_the_other_sessions(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    (tmp_path / "sessions" / "broken.meta.json").write_text("{not json", encoding="utf-8")

    assert [item.id for item in store.list()] == [session.id]


def test_the_meta_file_is_written_at_once(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)

    assert json.loads(store.meta_path(session.id).read_text(encoding="utf-8"))["id"] == session.id
    assert [path.name for path in (tmp_path / "sessions").iterdir() if path.name.endswith(".tmp")] == []


def test_the_events_are_on_the_disk_right_away(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    store.append(session.id, _message(session.id, "hello"))

    assert store.events(session.id)[-1].payload["content"] == "hello"
