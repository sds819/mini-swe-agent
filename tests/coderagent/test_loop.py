import json

import pytest

from coderagent.core.events import EventBus, EventType
from coderagent.core.loop import AgentLoop
from coderagent.core.session import SessionState, SessionStore
from coderagent.models.gateway import ModelGateway
from coderagent.testing.factory import build_context, build_executor
from coderagent.testing.scripted_model import ScriptedModel


def _bash_call(command: str, call_id: str = "call_1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "bash", "arguments": json.dumps({"command": command})},
    }


def _assistant(content: str = "", tool_calls: list[dict] | None = None, cost: float = 0.0) -> dict:
    return {"role": "assistant", "content": content, "tool_calls": tool_calls or [], "extra": {"cost": cost}}


def _loop(tmp_path, responses, **kwargs):
    store = SessionStore(tmp_path)
    session = store.create(tmp_path)
    bus = EventBus()
    model = ModelGateway(ScriptedModel(responses))
    executor = build_executor(tmp_path, store=store, context=build_context(tmp_path, session=session, bus=bus))
    loop = AgentLoop(
        model,
        executor,
        session,
        store,
        bus,
        tools=executor.registry.schemas(),
        **kwargs,
    )
    return loop, store, session, bus


def test_turn_executes_tool_call_and_finishes(tmp_path):
    loop, store, session, _ = _loop(
        tmp_path,
        [
            _assistant(tool_calls=[_bash_call("echo hello")], cost=0.1),
            _assistant(content="all done", cost=0.2),
        ],
    )
    result = loop.run_turn("say hello")

    assert result.stop_reason == "end_turn"
    assert result.cost == pytest.approx(0.3)
    assert [message["role"] for message in result.messages] == ["user", "assistant", "tool", "assistant"]
    assert "hello" in result.messages[2]["content"]
    assert result.messages[2]["tool_call_id"] == "call_1"

    events = store.events(session.id)
    assert [event.type for event in events] == [
        EventType.STATE_CHANGE,
        EventType.USER_MESSAGE,
        EventType.STATE_CHANGE,
        EventType.ASSISTANT_MESSAGE,
        EventType.STATE_CHANGE,
        EventType.TOOL_CALL,
        EventType.TOOL_RESULT,
        EventType.TOOL_RESULT,
        EventType.STATE_CHANGE,
        EventType.ASSISTANT_MESSAGE,
        EventType.STATE_CHANGE,
    ]
    """The result of the tool is in the log twice: once with the tool and the diff, once with the message."""
    assert store.rebuild(session.id).state == SessionState.DONE


def test_max_turns_stops_the_loop(tmp_path):
    loop, _, _, _ = _loop(
        tmp_path,
        [_assistant(tool_calls=[_bash_call("echo hi")]) for _ in range(5)],
        max_turns=2,
    )
    result = loop.run_turn("loop forever")
    assert result.stop_reason == "max_turns"


def test_cost_limit_stops_the_loop(tmp_path):
    loop, _, _, _ = _loop(
        tmp_path,
        [_assistant(tool_calls=[_bash_call("echo hi")], cost=1.0) for _ in range(5)],
        cost_limit=1.5,
    )
    result = loop.run_turn("spend money")
    assert result.stop_reason == "cost_exceeded"


def test_model_error_is_reported(tmp_path):
    loop, store, session, bus = _loop(tmp_path, [])
    result = loop.run_turn("trigger an error")
    assert result.stop_reason == "error"
    assert "AssertionError" in result.error
    assert any(event.type == EventType.ERROR for event in store.events(session.id))
    assert store.rebuild(session.id).state == SessionState.ERROR


def test_conversation_is_restored_from_the_event_log(tmp_path):
    loop, store, session, _ = _loop(tmp_path, [_assistant(content="done", cost=0.5)])
    loop.run_turn("first question")

    executor = build_executor(tmp_path)
    resumed = AgentLoop(
        ModelGateway(ScriptedModel([_assistant(content="still here")])),
        executor,
        store.rebuild(session.id),
        store,
        EventBus(),
        tools=executor.registry.schemas(),
    )
    assert [message["content"] for message in resumed.messages] == ["first question", "done"]
    result = resumed.run_turn("second question")
    assert result.messages[0] == {"role": "user", "content": "second question"}
    assert store.rebuild(session.id).turn_count == 2
