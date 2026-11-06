"""The response is normalized into the message shape the loop expects."""

from coderagent.models.backends import LiteLLMBackend


class _Message:
    def __init__(self, **fields):
        self._fields = fields

    def model_dump(self):
        return self._fields


class _Choice:
    def __init__(self, message):
        self.message = message


class _Response:
    def __init__(self, **fields):
        self.choices = [_Choice(_Message(**fields))]


def test_a_message_without_tool_calls_has_no_tool_calls_key():
    backend = LiteLLMBackend("test/model")
    assert backend._normalize(_Response(content="hello", tool_calls=[])) == {
        "role": "assistant",
        "content": "hello",
        "extra": {"cost": 0.0},
    }


def test_the_tool_calls_are_kept_when_they_exist():
    calls = [{"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}}]
    normalized = LiteLLMBackend("test/model")._normalize(_Response(content="", tool_calls=calls))
    assert normalized["tool_calls"] == calls
    assert normalized["content"] == ""


def test_missing_content_becomes_an_empty_string():
    normalized = LiteLLMBackend("test/model")._normalize(_Response(content=None))
    assert normalized["content"] == ""
