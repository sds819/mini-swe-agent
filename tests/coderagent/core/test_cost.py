"""The cost of a session: what this session spent, not what the process spent."""

import json

import pytest

from coderagent.core.events import EventBus
from coderagent.core.loop import AgentLoop
from coderagent.core.session import SessionStore
from coderagent.models.gateway import ModelGateway
from coderagent.testing.factory import build_executor
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
    executor = build_executor(tmp_path)
    loop = AgentLoop(
        ModelGateway(ScriptedModel(responses)),
        executor,
        session,
        store,
        EventBus(),
        tools=executor.registry.schemas(),
        **kwargs,
    )
    return loop, store, session


def test_a_session_pays_only_for_its_own_calls(tmp_path):
    """The gateway is shared by all the sessions of the process, the bill is not."""
    loop, store, session = _loop(tmp_path, [_assistant(content="one", cost=0.3), _assistant(content="two", cost=0.2)])
    loop.run_turn("first question")
    assert session.total_cost == pytest.approx(0.3)

    loop.switch_to(store.create(tmp_path))
    loop.run_turn("second question")
    assert loop.session.total_cost == pytest.approx(0.2)
    assert session.total_cost == pytest.approx(0.3)


def test_the_cost_of_a_session_is_the_cost_of_its_log(tmp_path):
    loop, store, session = _loop(tmp_path, [_assistant(content="one", cost=0.3)])
    loop.run_turn("a question")
    assert session.total_cost == store.rebuild(session.id).total_cost


def test_a_new_session_starts_with_a_full_budget(tmp_path):
    """The budget belongs to the session, a new one does not start with an exhausted one."""
    loop, store, session = _loop(
        tmp_path,
        [
            _assistant(tool_calls=[_bash_call("echo hi")], cost=2.0),
            _assistant(content="done", cost=0.1),
        ],
        cost_limit=1.5,
    )
    assert loop.run_turn("first question").stop_reason == "cost_exceeded"

    loop.switch_to(store.create(tmp_path))
    assert loop.run_turn("second question").stop_reason == "end_turn"
    assert loop.session.total_cost == pytest.approx(0.1)
