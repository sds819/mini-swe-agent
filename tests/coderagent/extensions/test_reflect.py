"""Settling the experience of a session in the memory."""

import json
from pathlib import Path

from coderagent.config.schema import Config, MemoryConfig
from coderagent.core.events import EventBus, EventType
from coderagent.core.session import SessionStore
from coderagent.core.telemetry import collect
from coderagent.extensions.reflect import (
    MAX_LINES,
    append_facts,
    append_user_preferences,
    clear_pending,
    forget,
    parse_reflection,
    pending_path,
    project_memory_path,
    read_pending,
    reflect_prompt,
    user_memory_path,
)
from coderagent.models.gateway import ModelGateway
from coderagent.models.streaming import ModelEvent
from coderagent.run import run_turn, settle_session
from coderagent.testing.scripted_model import ScriptedModel


def _memory(tmp_path) -> MemoryConfig:
    return MemoryConfig(project_path=".coderagent/memory", user_path="CLAUDE.md")


def _user_home(tmp_path) -> Path:
    return tmp_path / "user"


def _answer(**kwargs) -> str:
    return json.dumps(kwargs)


def test_the_prompt_holds_the_conversation():
    prompt = reflect_prompt([{"role": "user", "content": "fix the bug"}, {"role": "assistant", "content": "done"}])
    assert "fix the bug" in prompt
    assert "done" in prompt


def test_the_answer_of_the_model_is_read():
    reflection = parse_reflection(
        _answer(project_facts=["the tests need pytest -m slow"], user_preferences=["Chinese comments"])
    )
    assert reflection.project_facts == ["the tests need pytest -m slow"]
    assert reflection.user_preferences == ["Chinese comments"]


def test_an_answer_in_a_code_block_is_read():
    reflection = parse_reflection('```json\n{"project_facts": ["a fact"], "user_preferences": []}\n```')
    assert reflection.project_facts == ["a fact"]


def test_a_broken_answer_gives_nothing():
    assert parse_reflection("I have no idea").project_facts == []
    assert parse_reflection("").user_preferences == []


def test_the_facts_are_written_to_the_project_memory(tmp_path):
    path = project_memory_path(tmp_path, _memory(tmp_path))
    write = append_facts(path, ["the build is make build"], "# Project memory")
    assert write.written == ["the build is make build"]
    assert "the build is make build" in path.read_text(encoding="utf-8")


def test_a_fact_that_is_already_there_is_not_written_again(tmp_path):
    path = project_memory_path(tmp_path, _memory(tmp_path))
    append_facts(path, ["the build is make build"], "# Project memory")
    write = append_facts(path, ["The build is make build!"], "# Project memory")
    assert write.written == []
    assert path.read_text(encoding="utf-8").count("make build") == 1


def test_the_memory_does_not_grow_past_the_limit(tmp_path):
    path = tmp_path / "projects.md"
    path.write_text("\n".join(f"- fact {index}" for index in range(MAX_LINES)), encoding="utf-8")
    write = append_facts(path, ["one more"], "# Project memory")
    assert write.written == []
    assert "tidy it up" in write.warning


def test_the_preferences_of_the_user_go_under_their_own_heading(tmp_path):
    path = user_memory_path(_memory(tmp_path), _user_home(tmp_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# My instructions\n", encoding="utf-8")
    write = append_user_preferences(path, ["Chinese comments"])
    assert write.written == ["Chinese comments"]
    text = path.read_text(encoding="utf-8")
    assert "# My instructions" in text
    assert "## Preferences" in text
    assert "- Chinese comments" in text


def test_a_preference_is_not_written_twice(tmp_path):
    path = user_memory_path(_memory(tmp_path), _user_home(tmp_path))
    append_user_preferences(path, ["Chinese comments"])
    assert append_user_preferences(path, ["Chinese comments"]).written == []


def test_the_pending_preferences_wait_for_a_confirmation(tmp_path):
    append_facts(pending_path(tmp_path), ["no tabs"], "# Preferences waiting for a confirmation")
    assert read_pending(tmp_path) == ["no tabs"]
    assert clear_pending(tmp_path) == ["no tabs"]
    assert read_pending(tmp_path) == []


def test_a_fact_can_be_forgotten(tmp_path):
    path = project_memory_path(tmp_path, _memory(tmp_path))
    append_facts(path, ["the build is make build"], "# Project memory")
    assert forget(path, "the build is make build") is True
    assert "make build" not in path.read_text(encoding="utf-8")


def test_forgetting_something_that_is_not_there_says_so(tmp_path):
    assert forget(project_memory_path(tmp_path, _memory(tmp_path)), "nothing") is False


def _loop(tmp_path, answer: str, cost: float = 0.0):
    from coderagent.core.loop import AgentLoop
    from coderagent.testing.factory import build_executor

    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    executor = build_executor(tmp_path)
    loop = AgentLoop(
        ModelGateway(ScriptedModel([{"role": "assistant", "content": answer, "extra": {"cost": cost}}])),
        executor,
        session,
        store,
        EventBus(),
        tools=executor.registry.schemas(),
    )
    loop.context.append({"role": "user", "content": "fix the bug"})
    return loop


def test_the_session_is_settled_in_the_project_memory(tmp_path):
    config = Config()
    config.memory = _memory(tmp_path)
    loop = _loop(
        tmp_path, _answer(project_facts=["the tests need pytest -m slow"], user_preferences=["Chinese comments"])
    )
    settle_session(loop, config, tmp_path, user_home=_user_home(tmp_path))
    text = (project_memory_path(tmp_path, config.memory)).read_text(encoding="utf-8")
    assert "the tests need pytest -m slow" in text


def test_the_preferences_of_the_user_wait_when_nobody_confirms(tmp_path):
    config = Config()
    config.memory = _memory(tmp_path)
    loop = _loop(tmp_path, _answer(project_facts=[], user_preferences=["Chinese comments"]))
    settle_session(loop, config, tmp_path, user_home=_user_home(tmp_path))
    assert read_pending(tmp_path) == ["Chinese comments"]
    assert not user_memory_path(config.memory, _user_home(tmp_path)).exists()


def test_the_preferences_of_the_user_are_written_when_the_user_says_so(tmp_path):
    config = Config()
    config.memory = _memory(tmp_path)
    loop = _loop(tmp_path, _answer(project_facts=[], user_preferences=["Chinese comments"]))
    settle_session(loop, config, tmp_path, confirm=lambda preferences: True, user_home=_user_home(tmp_path))
    assert "Chinese comments" in user_memory_path(config.memory, _user_home(tmp_path)).read_text(encoding="utf-8")
    assert read_pending(tmp_path) == []


def test_a_session_without_messages_is_not_settled(tmp_path):
    config = Config()
    config.memory = _memory(tmp_path)
    from coderagent.core.loop import AgentLoop
    from coderagent.testing.factory import build_executor

    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    executor = build_executor(tmp_path)
    loop = AgentLoop(
        ModelGateway(ScriptedModel([])),
        executor,
        session,
        store,
        EventBus(),
        tools=executor.registry.schemas(),
    )
    assert settle_session(loop, config, tmp_path, user_home=_user_home(tmp_path)).project_facts == []
    assert not project_memory_path(tmp_path, config.memory).exists()


def test_the_reflection_is_in_the_event_log(tmp_path):
    """The call of the model is a call like any other: it is in the log."""
    config = Config()
    config.memory = _memory(tmp_path)
    loop = _loop(tmp_path, _answer(project_facts=["the tests need pytest -m slow"]), cost=0.25)
    settle_session(loop, config, tmp_path, user_home=_user_home(tmp_path))
    reflections = [e for e in loop.store.events(loop.session.id) if e.type == EventType.REFLECTION]
    assert len(reflections) == 1
    assert reflections[0].payload["cost"] == 0.25
    assert reflections[0].payload["purpose"] == "reflect"
    assert reflections[0].payload["project_facts"] == ["the tests need pytest -m slow"]


def test_the_cost_of_the_reflection_is_part_of_the_session(tmp_path):
    """The money of the reflection is the money of the session."""
    config = Config()
    config.memory = _memory(tmp_path)
    loop = _loop(tmp_path, _answer(project_facts=[]), cost=0.25)
    settle_session(loop, config, tmp_path, user_home=_user_home(tmp_path))
    assert loop.model.total_cost == 0.25
    assert loop.session.total_cost == 0.25
    assert collect(loop.store.events(loop.session.id)).total_cost == 0.25


def test_the_reflection_on_its_own_model_is_booked_on_the_main_one(tmp_path):
    """The reflection ran on another model, but the budget of the session still covers it."""
    config = Config()
    config.memory = _memory(tmp_path)
    loop = _loop(tmp_path, _answer(project_facts=[]))
    other = ModelGateway(ScriptedModel([{"role": "assistant", "content": _answer(), "extra": {"cost": 0.5}}]))
    settle_session(loop, config, tmp_path, gateway=other, user_home=_user_home(tmp_path))
    assert loop.model.total_cost == 0.5
    assert collect(loop.store.events(loop.session.id)).total_cost == 0.5
    assert other.total_cost == 0.5


def test_a_reflection_that_fails_is_still_paid_for(tmp_path):
    """The provider took the money before it failed: the cost is in the log anyway."""
    config = Config()
    config.memory = _memory(tmp_path)
    loop = _loop(tmp_path, _answer(project_facts=[]))

    class BrokenModel(ScriptedModel):
        def query_stream(self, messages, tools=None, **kwargs):
            yield ModelEvent(type="usage", cost=0.3)
            raise RuntimeError("the provider is down")

    settle_session(loop, config, tmp_path, gateway=ModelGateway(BrokenModel()), user_home=_user_home(tmp_path))
    reflections = [e for e in loop.store.events(loop.session.id) if e.type == EventType.REFLECTION]
    assert reflections[0].payload["cost"] == 0.3
    assert loop.model.total_cost == 0.3
    assert collect(loop.store.events(loop.session.id)).total_cost == 0.3


def test_a_headless_run_settles_the_session(tmp_path):
    """A session that ends is settled in the memory, the same way as in the interface."""
    config = Config()
    config.memory = _memory(tmp_path)
    model = ScriptedModel(
        [
            {"role": "assistant", "content": "done"},
            {"role": "assistant", "content": _answer(project_facts=["the tests need pytest -m slow"])},
        ]
    )
    store = SessionStore(tmp_path / "sessions")
    run_turn("fix the bug", config, cwd=tmp_path, model=model, store=store)
    text = project_memory_path(tmp_path, config.memory).read_text(encoding="utf-8")
    assert "the tests need pytest -m slow" in text
    events = [event for session in store.list(tmp_path) for event in store.events(session.id)]
    assert [event for event in events if event.type == EventType.REFLECTION]


def test_a_run_does_not_settle_when_the_memory_is_off(tmp_path):
    """The memory is off: the model is not even asked."""
    config = Config()
    config.memory = _memory(tmp_path)
    config.memory.enabled = False
    model = ScriptedModel([{"role": "assistant", "content": "done"}])
    run_turn("fix the bug", config, cwd=tmp_path, model=model, store=SessionStore(tmp_path / "sessions"))
    assert len(model.calls) == 1
    assert not project_memory_path(tmp_path, config.memory).exists()


def test_a_run_survives_a_reflection_that_fails(tmp_path):
    """The reflection is a nice extra: it must not break the run."""
    config = Config()
    config.memory = _memory(tmp_path)
    model = ScriptedModel([{"role": "assistant", "content": "done"}])
    result = run_turn("fix the bug", config, cwd=tmp_path, model=model, store=SessionStore(tmp_path / "sessions"))
    assert result.stop_reason == "end_turn"
    assert not project_memory_path(tmp_path, config.memory).exists()


def test_a_run_that_failed_is_not_settled(tmp_path):
    """The model is down: there is nothing to remember and no model to ask."""
    config = Config()
    config.memory = _memory(tmp_path)

    def side_effect(messages):
        if len(model.calls) == 1:
            raise RuntimeError("the provider is down")
        return {"role": "assistant", "content": _answer(project_facts=["a fact"])}

    model = ScriptedModel(side_effect=side_effect)
    result = run_turn("fix the bug", config, cwd=tmp_path, model=model, store=SessionStore(tmp_path / "sessions"))
    assert result.stop_reason == "error"
    assert len(model.calls) == 1
    assert not project_memory_path(tmp_path, config.memory).exists()


def test_a_run_that_ran_out_of_budget_is_not_settled(tmp_path):
    """The budget is gone: the reflection must not spend more."""
    config = Config()
    config.memory = _memory(tmp_path)
    config.agent.cost_limit = 0.05
    call = {"id": "c1", "type": "function", "function": {"name": "bash", "arguments": json.dumps({"command": "ls"})}}
    model = ScriptedModel([{"role": "assistant", "content": "", "tool_calls": [call], "extra": {"cost": 0.1}}])
    result = run_turn("fix the bug", config, cwd=tmp_path, model=model, store=SessionStore(tmp_path / "sessions"))
    assert result.stop_reason == "cost_exceeded"
    assert len(model.calls) == 1
