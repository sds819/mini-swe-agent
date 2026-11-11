"""The verification loop: the agent must make the commands pass before it stops."""

import json

from coderagent.config.schema import VerifyConfig
from coderagent.core.events import EventBus, EventType
from coderagent.core.loop import AgentLoop
from coderagent.core.session import SessionStore
from coderagent.models.gateway import ModelGateway
from coderagent.testing.factory import build_context, build_executor
from coderagent.testing.scripted_model import ScriptedModel


def _assistant(content: str = "", tool_calls: list[dict] | None = None) -> dict:
    return {"role": "assistant", "content": content, "tool_calls": tool_calls or [], "extra": {"cost": 0.0}}


def _write_call(path: str, content: str, call_id: str = "call_1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "write", "arguments": json.dumps({"path": path, "content": content})},
    }


def _loop(tmp_path, responses, verify: VerifyConfig):
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    bus = EventBus()
    executor = build_executor(tmp_path, store=store, context=build_context(tmp_path, session=session, bus=bus))
    loop = AgentLoop(
        ModelGateway(ScriptedModel(responses)),
        executor,
        session,
        store,
        bus,
        tools=executor.registry.schemas(),
        verify=verify,
    )
    return loop, store, session


def test_the_work_that_passes_the_check_ends_the_turn(tmp_path):
    (tmp_path / "a.py").write_text("ok\n", encoding="utf-8")
    loop, store, session = _loop(
        tmp_path,
        [_assistant(content="done")],
        VerifyConfig(commands=["grep -q ok a.py"]),
    )
    result = loop.run_turn("do it")
    assert result.stop_reason == "end_turn"
    assert len(store.events(session.id)) > 0
    assert not [
        event for event in store.events(session.id) if event.type == EventType.VERIFY and event.payload["failed"]
    ]


def test_a_failing_check_gives_the_agent_a_second_try(tmp_path):
    (tmp_path / "a.py").write_text("ok\n", encoding="utf-8")
    loop, store, session = _loop(
        tmp_path,
        [
            _assistant(content="all done"),
            _assistant(tool_calls=[_write_call("a.py", "fixed\n")]),
            _assistant(content="now it passes"),
        ],
        VerifyConfig(commands=["grep -q fixed a.py"]),
    )
    result = loop.run_turn("do it")
    assert result.stop_reason == "end_turn"
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "fixed\n"
    contents = [message.get("content", "") for message in result.messages]
    assert any("[verify]" in content for content in contents)


def test_the_failure_of_a_check_is_in_the_log(tmp_path):
    (tmp_path / "a.py").write_text("ok\n", encoding="utf-8")
    loop, store, session = _loop(
        tmp_path,
        [_assistant(content="done"), _assistant(content="done again")],
        VerifyConfig(commands=["grep -q fixed a.py"], max_rounds=1),
    )
    loop.run_turn("do it")
    verifies = [event for event in store.events(session.id) if event.type == EventType.VERIFY]
    assert verifies[0].payload["failed"] == ["grep -q fixed a.py"]


def test_a_check_that_never_passes_ends_the_turn_with_a_reason(tmp_path):
    (tmp_path / "a.py").write_text("ok\n", encoding="utf-8")
    loop, _, _ = _loop(
        tmp_path,
        [_assistant(content="done"), _assistant(content="done again")],
        VerifyConfig(commands=["grep -q fixed a.py"], max_rounds=1),
    )
    result = loop.run_turn("do it")
    assert result.stop_reason == "verify_failed"
    assert "[verify]" in result.error


def test_without_commands_nothing_is_verified(tmp_path):
    loop, store, session = _loop(tmp_path, [_assistant(content="done")], VerifyConfig())
    result = loop.run_turn("do it")
    assert result.stop_reason == "end_turn"
    assert not [event for event in store.events(session.id) if event.type == EventType.VERIFY]
