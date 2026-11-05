import pytest

from coderagent.core.events import Event, EventBus, EventType


def test_publish_is_ordered():
    bus = EventBus()
    seen = []
    bus.subscribe(EventType.USER_MESSAGE, lambda e: seen.append(("a", e)))
    bus.subscribe(EventType.USER_MESSAGE, lambda e: seen.append(("b", e)))
    event = Event(EventType.USER_MESSAGE, "s1", 1.0, {"content": "hi"})
    bus.publish(event)
    assert [name for name, _ in seen] == ["a", "b"]
    assert seen[0][1] is event


def test_failing_subscriber_does_not_break_others():
    bus = EventBus()
    seen = []

    def boom(event):
        raise RuntimeError("subscriber failed")

    bus.subscribe(EventType.USER_MESSAGE, boom)
    bus.subscribe(EventType.USER_MESSAGE, lambda e: seen.append(e))
    bus.publish(Event(EventType.USER_MESSAGE, "s1", 1.0))
    assert len(seen) == 1


def test_event_roundtrip():
    event = Event(EventType.TOOL_RESULT, "s1", 12.5, {"messages": [{"role": "tool"}]})
    restored = Event.from_dict(event.to_dict())
    assert restored == event


def test_unknown_event_type_is_skipped():
    assert Event.from_dict({"type": "not_a_real_type", "session_id": "s1"}) is None
    assert Event.from_dict({}) is None


def test_unsubscribed_type_is_ignored():
    bus = EventBus()
    bus.subscribe(EventType.ERROR, lambda e: pytest.fail("should not be called"))
    bus.publish(Event(EventType.USER_MESSAGE, "s1", 1.0))
