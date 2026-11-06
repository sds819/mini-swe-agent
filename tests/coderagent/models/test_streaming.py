"""The pieces of a streamed answer are put back together."""

import pytest

from coderagent.models.streaming import ModelEvent, ToolCallAccumulator, message_from_events
from minisweagent.exceptions import FormatError


def test_the_arguments_of_a_tool_call_are_joined():
    accumulator = ToolCallAccumulator()
    accumulator.feed({"index": 0, "id": "c1", "function": {"name": "read", "arguments": '{"pa'}})
    accumulator.feed({"index": 0, "function": {"arguments": 'th": "a.py"}'}})
    assert accumulator.finish() == [
        {"id": "c1", "type": "function", "function": {"name": "read", "arguments": '{"path": "a.py"}'}}
    ]


def test_parallel_tool_calls_stay_apart():
    accumulator = ToolCallAccumulator()
    accumulator.feed({"index": 0, "id": "c1", "function": {"name": "read", "arguments": "{}"}})
    accumulator.feed({"index": 1, "id": "c2", "function": {"name": "ls", "arguments": "{}"}})
    calls = accumulator.finish()
    assert [call["id"] for call in calls] == ["c1", "c2"]
    assert [call["function"]["name"] for call in calls] == ["read", "ls"]


def test_a_repeated_name_is_not_counted_twice():
    accumulator = ToolCallAccumulator()
    accumulator.feed({"index": 0, "function": {"name": "read", "arguments": "{}"}})
    accumulator.feed({"index": 0, "function": {"name": "read", "arguments": ""}})
    assert accumulator.finish()[0]["function"]["name"] == "read"


def test_a_name_that_arrives_in_pieces_is_joined():
    accumulator = ToolCallAccumulator()
    accumulator.feed({"index": 0, "function": {"name": "re", "arguments": "{}"}})
    accumulator.feed({"index": 0, "function": {"name": "ad", "arguments": ""}})
    assert accumulator.finish()[0]["function"]["name"] == "read"


def test_broken_arguments_are_reported():
    accumulator = ToolCallAccumulator()
    accumulator.feed({"index": 0, "function": {"name": "read", "arguments": "{not json"}})
    with pytest.raises(FormatError, match="read"):
        accumulator.finish()


def test_the_text_of_the_events_becomes_the_content():
    events = [ModelEvent(type="text", content="hel"), ModelEvent(type="text", content="lo")]
    assert message_from_events(events)["content"] == "hello"


def test_the_reasoning_is_not_mixed_into_the_text():
    events = [ModelEvent(type="reasoning", content="thinking"), ModelEvent(type="text", content="answer")]
    message = message_from_events(events)
    assert message["content"] == "answer"
    assert message["extra"]["reasoning"] == "thinking"


def test_a_message_without_tool_calls_has_no_tool_calls_key():
    assert "tool_calls" not in message_from_events([ModelEvent(type="text", content="hi")])


def test_the_cost_of_the_usage_is_added_up():
    events = [ModelEvent(type="usage", cost=0.1), ModelEvent(type="usage", cost=0.2)]
    assert message_from_events(events)["extra"]["cost"] == pytest.approx(0.3)
