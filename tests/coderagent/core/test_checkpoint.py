"""Checkpoints: what the files looked like before the agent changed them."""

import pytest

from coderagent.config.schema import ContextConfig
from coderagent.core.checkpoint import CheckpointStore, create_file_checkpoint, restore_files
from coderagent.core.context import ContextEngine
from coderagent.core.events import EventBus
from coderagent.core.session import SessionStore
from coderagent.ui.commands.rewind import list_checkpoints, rewind


def _store(tmp_path) -> CheckpointStore:
    return CheckpointStore(root=tmp_path / "checkpoints")


def _context(tmp_path) -> ContextEngine:
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    return ContextEngine(session, store, EventBus(), ContextConfig(), None, cwd=tmp_path, user_home=tmp_path / "home")


def test_a_checkpoint_keeps_the_old_content(tmp_path):
    (tmp_path / "a.py").write_text("old", encoding="utf-8")
    store = _store(tmp_path)
    checkpoint = create_file_checkpoint(store, "session", 3, tmp_path, "a.py")
    assert checkpoint.kind == "file_diff"
    assert checkpoint.payload == {"a.py": "old"}
    assert checkpoint.turn == 3
    assert store.get("session", checkpoint.id).payload == {"a.py": "old"}


def test_a_file_that_does_not_exist_yet_is_remembered_as_missing(tmp_path):
    store = _store(tmp_path)
    checkpoint = create_file_checkpoint(store, "session", 1, tmp_path, "new.py")
    assert checkpoint.payload == {"new.py": None}


def test_the_checkpoint_survives_a_restart(tmp_path):
    (tmp_path / "a.py").write_text("old", encoding="utf-8")
    store = _store(tmp_path)
    create_file_checkpoint(store, "session", 1, tmp_path, "a.py")
    assert [checkpoint.payload for checkpoint in store.all("session")] == [{"a.py": "old"}]


def test_only_the_last_checkpoints_are_kept(tmp_path):
    store = _store(tmp_path)
    store.keep = 2
    for index in range(5):
        store.create("session", index, "file_diff", {"a.py": f"v{index}"})
    assert len(store.all("session")) == 2
    assert store.all("session")[0].payload == {"a.py": "v3"}


def test_restoring_puts_the_old_content_back(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("new", encoding="utf-8")
    checkpoint = type("C", (), {"payload": {"a.py": "old"}})()
    assert restore_files(checkpoint, tmp_path) == ["a.py"]
    assert target.read_text(encoding="utf-8") == "old"


def test_restoring_removes_a_file_that_did_not_exist_before(tmp_path):
    target = tmp_path / "new.py"
    target.write_text("new", encoding="utf-8")
    checkpoint = type("C", (), {"payload": {"new.py": None}})()
    assert restore_files(checkpoint, tmp_path) == ["new.py"]
    assert not target.exists()


def test_restoring_an_unchanged_file_does_nothing(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("same", encoding="utf-8")
    checkpoint = type("C", (), {"payload": {"a.py": "same"}})()
    assert restore_files(checkpoint, tmp_path) == []


def test_rewinding_restores_the_files_and_the_conversation(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("old", encoding="utf-8")
    context = _context(tmp_path)
    context.append({"role": "user", "content": "change it"})
    store = _store(tmp_path)
    checkpoint = create_file_checkpoint(store, context.session.id, 1, tmp_path, "a.py", len(context.history.messages))
    target.write_text("new", encoding="utf-8")
    context.append({"role": "assistant", "content": "done"})

    assert rewind(context, store, checkpoint.id, tmp_path) == ["a.py"]
    assert target.read_text(encoding="utf-8") == "old"
    assert [message["role"] for message in context.history.messages] == ["user"]


def test_rewinding_an_unknown_checkpoint_is_an_error(tmp_path):
    context = _context(tmp_path)
    with pytest.raises(ValueError, match="nope"):
        rewind(context, _store(tmp_path), "nope", tmp_path)


def test_the_checkpoints_of_a_session_are_listed(tmp_path):
    context = _context(tmp_path)
    store = _store(tmp_path)
    create_file_checkpoint(store, context.session.id, 1, tmp_path, "a.py")
    create_file_checkpoint(store, context.session.id, 2, tmp_path, "b.py")
    assert [checkpoint.turn for checkpoint in list_checkpoints(store, context.session.id)] == [1, 2]


def test_the_rewind_survives_a_restart(tmp_path):
    context = _context(tmp_path)
    context.append({"role": "user", "content": "change it"})
    context.rewind_to(0)
    restored = ContextEngine(
        context.session,
        context.store,
        EventBus(),
        ContextConfig(),
        None,
        cwd=tmp_path,
        user_home=tmp_path / "home",
    )
    restored.restore()
    assert restored.history.messages == []


def test_a_write_tool_takes_a_checkpoint_first(tmp_path):
    import json

    from coderagent.core.loop import AgentLoop
    from coderagent.models.gateway import ModelGateway
    from coderagent.testing.factory import build_context, build_executor
    from coderagent.testing.scripted_model import ScriptedModel
    from coderagent.tools.permissions import PermissionMode, PermissionPolicy

    (tmp_path / "a.py").write_text("old\n", encoding="utf-8")
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    bus = EventBus()
    policy = PermissionPolicy(PermissionMode.BYPASS, [], cwd=tmp_path)
    ctx = build_context(tmp_path, session=session, bus=bus, policy=policy)
    checkpoints = _store(tmp_path)
    executor = build_executor(tmp_path, context=ctx)
    executor.before_write = lambda tool, params: create_file_checkpoint(
        checkpoints, session.id, session.turn_count, tmp_path, params["path"], 0
    )
    loop = AgentLoop(
        ModelGateway(
            ScriptedModel(
                [
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {
                                    "name": "write",
                                    "arguments": json.dumps({"path": "a.py", "content": "new\n"}),
                                },
                            }
                        ],
                        "extra": {"cost": 0.0},
                    },
                    {"role": "assistant", "content": "written", "extra": {"cost": 0.0}},
                ]
            )
        ),
        executor,
        session,
        store,
        bus,
        tools=executor.registry.schemas(),
    )
    loop.run_turn("rewrite the file")

    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "new\n"
    assert [checkpoint.payload for checkpoint in checkpoints.all(session.id)] == [{"a.py": "old\n"}]
