"""The response is normalized into the message shape the loop expects."""

from coderagent.models.backends import LiteLLMBackend
from coderagent.models.streaming import ModelEvent, message_from_events


class _Delta:
    def __init__(self, **fields) -> None:
        self.__dict__.update(fields)


class _Choice:
    def __init__(self, delta) -> None:
        self.delta = delta


class _Chunk:
    def __init__(self, content=None, reasoning_content=None, tool_calls=None, usage=None) -> None:
        self.choices = [_Choice(_Delta(content=content, reasoning_content=reasoning_content, tool_calls=tool_calls))]
        self.usage = usage


def test_a_message_without_tool_calls_has_no_tool_calls_key():
    message = message_from_events([ModelEvent(type="text", content="hello")])
    assert message == {"role": "assistant", "content": "hello", "extra": {"cost": 0.0}}


def test_the_tool_calls_are_kept_when_they_exist():
    call = {"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}}
    message = message_from_events([ModelEvent(type="tool_call_done", tool_call=call)])
    assert message["tool_calls"] == [call]
    assert message["content"] == ""


def test_the_reasoning_is_kept_out_of_the_text():
    message = message_from_events(
        [ModelEvent(type="reasoning", content="thinking"), ModelEvent(type="text", content="answer")]
    )
    assert message["content"] == "answer"
    assert message["extra"]["reasoning"] == "thinking"


def test_the_cost_is_booked():
    message = message_from_events([ModelEvent(type="text", content="hi"), ModelEvent(type="usage", cost=0.25)])
    assert message["extra"]["cost"] == 0.25


def test_the_backend_reads_the_events_of_a_stream():
    backend = LiteLLMBackend("test/model")
    chunks = [
        _Chunk(content="he", reasoning_content="think"),
        _Chunk(content="llo", tool_calls=[{"index": 0, "id": "c1", "function": {"name": "read", "arguments": '{"pa'}}]),
        _Chunk(tool_calls=[{"index": 0, "function": {"arguments": 'th": "a.py"}'}}]),
    ]
    events = list(backend._events(chunks))
    assert [event.type for event in events] == [
        "reasoning",
        "text",
        "text",
        "tool_call_delta",
        "tool_call_delta",
        "tool_call_done",
    ]
    assert events[-1].tool_call == {
        "id": "c1",
        "type": "function",
        "function": {"name": "read", "arguments": '{"path": "a.py"}'},
    }


def test_the_text_of_a_stream_becomes_one_message():
    backend = LiteLLMBackend("test/model")
    chunks = [_Chunk(content="he"), _Chunk(content="llo")]
    message = message_from_events(backend._events(chunks))
    assert message["content"] == "hello"
