import json

from coderagent.core.events import EventBus
from coderagent.core.loop import AgentLoop
from coderagent.core.session import SessionStore
from coderagent.models.gateway import ModelGateway
from coderagent.testing.factory import build_context, build_executor
from coderagent.testing.scripted_model import ScriptedModel
from coderagent.tools.permissions import PermissionMode, PermissionPolicy


def _call(name: str, arguments: dict, call_id: str) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def _assistant(tool_calls: list[dict] | None = None, content: str = "") -> dict:
    return {"role": "assistant", "content": content, "tool_calls": tool_calls or [], "extra": {"cost": 0.0}}


def _loop(tmp_path, responses, mode=PermissionMode.ACCEPT_EDITS):
    store = SessionStore(tmp_path)
    session = store.create(tmp_path)
    bus = EventBus()
    policy = PermissionPolicy(mode, [], cwd=tmp_path)
    ctx = build_context(tmp_path, session=session, bus=bus, policy=policy)
    executor = build_executor(tmp_path, context=ctx)
    return (
        AgentLoop(
            ModelGateway(ScriptedModel(responses)),
            executor,
            session,
            store,
            bus,
            tools=executor.registry.schemas(),
        ),
        store,
        session,
    )


def test_the_agent_reads_edits_and_searches(tmp_path):
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    loop, store, session = _loop(
        tmp_path,
        [
            _assistant([_call("read", {"path": "calc.py"}, "c1")]),
            _assistant([_call("edit", {"path": "calc.py", "old_string": "a - b", "new_string": "a + b"}, "c2")]),
            _assistant([_call("grep", {"pattern": "a \\+ b"}, "c3")]),
            _assistant(content="fixed the sign"),
        ],
    )
    result = loop.run_turn("fix the subtraction in calc.py")

    assert result.stop_reason == "end_turn"
    assert (tmp_path / "calc.py").read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"
    assert "calc.py:2:    return a + b" in result.messages[6]["content"]
    assert store.rebuild(session.id).turn_count == 1


def test_an_edit_outside_the_working_directory_is_refused(tmp_path):
    outside = tmp_path.parent / "outside.py"
    outside.write_text("original\n", encoding="utf-8")
    loop, _, _ = _loop(
        tmp_path,
        [
            _assistant([_call("edit", {"path": str(outside), "old_string": "original", "new_string": "hacked"}, "c1")]),
            _assistant(content="I could not do that"),
        ],
        mode=PermissionMode.BYPASS,
    )
    result = loop.run_turn("break the file next door")

    assert "permission denied" in result.messages[2]["content"]
    assert outside.read_text(encoding="utf-8") == "original\n"


def test_a_write_is_refused_in_readonly_mode(tmp_path):
    (tmp_path / "a.py").write_text("original\n", encoding="utf-8")
    loop, _, _ = _loop(
        tmp_path,
        [
            _assistant([_call("write", {"path": "a.py", "content": "new\n"}, "c1")]),
            _assistant(content="I could not do that"),
        ],
        mode=PermissionMode.READONLY,
    )
    result = loop.run_turn("overwrite the file")

    assert "permission denied" in result.messages[2]["content"]
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "original\n"


def test_the_task_list_survives_a_restart(tmp_path):
    loop, store, session = _loop(
        tmp_path,
        [
            _assistant([_call("todo_write", {"todos": [{"content": "write the fix", "status": "in_progress"}]}, "c1")]),
            _assistant(content="on it"),
        ],
    )
    loop.run_turn("plan the work")
    assert store.rebuild(session.id).metadata["todos"] == [{"content": "write the fix", "status": "in_progress"}]
