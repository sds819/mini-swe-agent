import pytest

from coderagent.testing.scripted_model import ScriptedModel


def test_responses_are_consumed_in_order():
    model = ScriptedModel([{"content": "first"}, {"content": "second"}])
    assert model.query([])["content"] == "first"
    assert model.query([])["content"] == "second"


def test_exhausted_model_raises_clear_error():
    model = ScriptedModel([{"content": "only"}])
    model.query([])
    with pytest.raises(AssertionError, match="ran out of responses after 2 calls"):
        model.query([])


def test_side_effect_receives_messages():
    model = ScriptedModel(side_effect=lambda messages: {"content": messages[-1]["content"]})
    assert model.query([{"role": "user", "content": "hello"}])["content"] == "hello"
    assert model.calls == [[{"role": "user", "content": "hello"}]]


def test_query_stream_yields_the_scripted_response():
    model = ScriptedModel([{"content": "streamed"}])
    assert [message["content"] for message in model.query_stream([])] == ["streamed"]
