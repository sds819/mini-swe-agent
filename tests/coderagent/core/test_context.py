"""What the model sees: system prompt, instructions, summary, then the recent history."""

from pathlib import Path

from coderagent.config.schema import ContextConfig, MemoryConfig
from coderagent.core.context import ContextEngine
from coderagent.core.events import EventBus
from coderagent.core.session import SessionStore
from coderagent.tools.permissions import PermissionMode, PermissionPolicy


class FakeModel:
    """A model that answers with a fixed text."""

    def __init__(self, answer: str = '{"goal": "g"}') -> None:
        self.answer = answer
        self.calls = 0

    def complete(self, messages, **kwargs) -> str:
        self.calls += 1
        return self.answer

    def query(self, messages, tools=None, **kwargs) -> dict:
        self.calls += 1
        return {"role": "assistant", "content": self.answer}


def make_engine(tmp_path: Path, **kwargs) -> ContextEngine:
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    return ContextEngine(
        session,
        store,
        EventBus(),
        kwargs.pop("config", ContextConfig()),
        kwargs.pop("model", FakeModel()),
        cwd=tmp_path,
        user_home=tmp_path / "home",
        **kwargs,
    )


def test_build_messages_order_is_system_instructions_summary_history(tmp_path):
    (tmp_path / "AGENTS.md").write_text("be careful", encoding="utf-8")
    engine = make_engine(tmp_path, system_prompt="you are a coder")
    engine.append({"role": "user", "content": "hello"})
    messages = engine.build_messages()
    assert messages[0] == {"role": "system", "content": "you are a coder"}
    assert "be careful" in messages[1]["content"]
    assert messages[2] == {"role": "user", "content": "hello"}


def test_the_summary_comes_before_the_history(tmp_path):
    from coderagent.core.summarize import Summary

    engine = make_engine(tmp_path, system_prompt="sys")
    engine.append({"role": "user", "content": "hello"})
    engine.summaries = [Summary(goal="the old goal")]
    messages = engine.build_messages()
    assert "<session_summary>" in messages[1]["content"]
    assert messages[2]["content"] == "hello"


def test_the_whole_history_is_sent_not_only_the_last_turns(tmp_path):
    engine = make_engine(tmp_path)
    for index in range(5):
        engine.append({"role": "user", "content": f"question {index}"})
        engine.append({"role": "assistant", "content": f"answer {index}"})
    assert len(engine.build_messages()) == 10


def test_without_a_system_prompt_the_first_message_is_the_instructions(tmp_path):
    (tmp_path / "AGENTS.md").write_text("be careful", encoding="utf-8")
    engine = make_engine(tmp_path)
    messages = engine.build_messages()
    assert messages[0]["role"] == "user"
    assert "be careful" in messages[0]["content"]


def test_the_todos_are_part_of_the_instructions(tmp_path):
    engine = make_engine(tmp_path)
    engine.session.metadata["todos"] = [
        {"content": "write the parser", "status": "in_progress"},
        {"content": "write the tests", "status": "completed"},
    ]
    text = engine._instruction_text()
    assert "- [ ] write the parser" in text
    assert "- [x] write the tests" in text


def test_the_window_cuts_on_a_turn_boundary(tmp_path):
    config = ContextConfig(keep_recent_turns=1, keep_recent_token_ratio=0.0)
    engine = make_engine(tmp_path, config=config)
    engine.append({"role": "user", "content": "q0"})
    engine.append({"role": "assistant", "content": "a0", "tool_calls": [{"id": "1", "function": {"name": "read"}}]})
    engine.append({"role": "tool", "tool_call_id": "1", "content": "the file"})
    engine.append({"role": "user", "content": "q1"})
    assert engine._cut_index() == 3
    assert engine.history.messages[engine._cut_index()]["content"] == "q1"


def test_the_token_ratio_keeps_more_of_the_history(tmp_path):
    config = ContextConfig(context_window=100, reserved_output=0, keep_recent_turns=1, keep_recent_token_ratio=0.0)
    engine = make_engine(tmp_path, config=config)
    for index in range(10):
        engine.append({"role": "user", "content": f"q{index}"})
        engine.append({"role": "assistant", "content": f"a{index}"})
    assert engine._cut_index() == 18
    engine.config.keep_recent_token_ratio = 0.4
    assert engine._cut_index() < 18


def test_the_user_memory_and_the_project_memory_are_loaded(tmp_path):
    memory_dir = tmp_path / ".coderagent" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "notes.md").write_text("the project memory", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    (home / "CLAUDE.md").write_text("the user memory", encoding="utf-8")
    engine = make_engine(tmp_path, memory_config=MemoryConfig())
    text = engine._instruction_text()
    assert "the project memory" in text
    assert "the user memory" in text


def test_the_memory_can_be_switched_off(tmp_path):
    memory_dir = tmp_path / ".coderagent" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "notes.md").write_text("the project memory", encoding="utf-8")
    engine = make_engine(tmp_path, memory_config=MemoryConfig(enabled=False))
    assert "the project memory" not in engine._instruction_text()


def test_restore_rebuilds_the_history_from_the_events(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    engine = ContextEngine(session, store, EventBus(), ContextConfig(), FakeModel(), cwd=tmp_path)
    engine.append({"role": "user", "content": "hello"})
    engine.append({"role": "assistant", "content": "hi"})
    restored = ContextEngine(session, store, EventBus(), ContextConfig(), FakeModel(), cwd=tmp_path)
    restored.restore()
    assert restored.history.messages == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]


def test_estimated_tokens_grows_with_the_history(tmp_path):
    engine = make_engine(tmp_path)
    before = engine.estimated_tokens()
    engine.append({"role": "user", "content": "x" * 1000})
    assert engine.estimated_tokens() > before


def test_the_model_is_told_about_the_permission_mode(tmp_path):
    policy = PermissionPolicy(PermissionMode.READONLY, [], cwd=tmp_path)
    engine = make_engine(tmp_path, policy=policy)
    contents = [message["content"] for message in engine.build_messages()]
    assert any('<permission_mode mode="readonly">' in content for content in contents)


def test_the_note_follows_the_mode_when_it_changes(tmp_path):
    policy = PermissionPolicy(PermissionMode.DEFAULT, [], cwd=tmp_path)
    engine = make_engine(tmp_path, policy=policy)
    assert not any("permission_mode" in message["content"] for message in engine.build_messages())
    policy.mode = PermissionMode.PLAN
    assert any('<permission_mode mode="plan">' in message["content"] for message in engine.build_messages())
