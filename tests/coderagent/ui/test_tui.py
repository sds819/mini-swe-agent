"""The terminal interface: the widgets and the app."""

import asyncio
import threading
import time

import pytest

from coderagent.config.schema import Config
from coderagent.core.events import EventBus, EventType
from coderagent.run import build_loop
from coderagent.testing.scripted_model import ScriptedModel
from coderagent.tools.permissions import ApprovalDecision
from coderagent.ui.widgets.diff_view import make_diff, prospective_diff
from coderagent.ui.widgets.tool_card import summarize

pytest.importorskip("textual")

from coderagent.ui.tui import CoderApp, TUIAprover  # noqa: E402
from coderagent.ui.widgets import MessageBlock, ToolCard  # noqa: E402


def _app(tmp_path, responses=None, mode="default"):
    config = Config()
    config.permissions.mode = mode
    bus = EventBus()
    approver = TUIAprover(bus)
    model = ScriptedModel(responses or [{"role": "assistant", "content": "hello", "extra": {"cost": 0.0}}])
    loop = build_loop(config, tmp_path, bus=bus, approver=approver, model=model)
    return CoderApp(config, tmp_path, bus=bus, approver=approver, store=loop.store, session=loop.session, loop=loop)


async def _wait_for(predicate, timeout=10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


def _assistant_blocks(app) -> list:
    return [block for block in app.query(MessageBlock) if block.role == "assistant"]


def test_the_diff_of_two_texts():
    diff = make_diff("one\ntwo\n", "one\nthree\n", "a.py")
    assert "-two" in diff
    assert "+three" in diff
    assert "a/a.py" in diff


def test_the_diff_a_tool_is_about_to_make(tmp_path):
    (tmp_path / "a.py").write_text("one\ntwo\n", encoding="utf-8")
    diff = prospective_diff("edit", {"path": "a.py", "old_string": "two", "new_string": "three"}, tmp_path)
    assert "-two" in diff
    assert "+three" in diff


def test_the_diff_of_a_new_file(tmp_path):
    diff = prospective_diff("write", {"path": "b.py", "content": "hello\n"}, tmp_path)
    assert "+hello" in diff


def test_the_summary_of_the_arguments():
    assert summarize({"path": "a.py"}) == "path=a.py"
    assert summarize({"command": "ls"}) == "command=ls"
    assert summarize({}) == ""


def test_the_app_shows_the_answer(tmp_path):
    app = _app(tmp_path)
    blocks = []

    async def go():
        async with app.run_test() as pilot:
            await pilot.press(*"hello")
            await pilot.press("enter")
            assert await _wait_for(lambda: _assistant_blocks(app))
            blocks.extend(_assistant_blocks(app))

    asyncio.run(go())
    assert blocks[0].content == "hello"


def test_the_status_bar_shows_the_session(tmp_path):
    app = _app(tmp_path)
    bar = []

    async def go():
        async with app.run_test():
            await asyncio.sleep(0.1)
            bar.append(app.query_one("StatusBar"))

    asyncio.run(go())
    assert bar[0].model == app.loop.model.backend.model_name
    assert bar[0].mode == "default"


def test_a_command_is_answered(tmp_path):
    app = _app(tmp_path)
    blocks = []

    async def go():
        async with app.run_test() as pilot:
            await pilot.press(*"/help")
            await pilot.press("enter")
            assert await _wait_for(lambda: _assistant_blocks(app))
            blocks.extend(_assistant_blocks(app))

    asyncio.run(go())
    assert "compact" in blocks[0].content


def test_the_card_of_a_tool_call_is_shown(tmp_path):
    call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "bash", "arguments": '{"command": "echo hi"}'},
    }
    app = _app(
        tmp_path,
        responses=[
            {"role": "assistant", "content": "", "tool_calls": [call], "extra": {"cost": 0.0}},
            {"role": "assistant", "content": "done", "extra": {"cost": 0.0}},
        ],
        mode="bypass",
    )
    cards = []

    async def go():
        async with app.run_test() as pilot:
            await pilot.press(*"run it")
            await pilot.press("enter")
            assert await _wait_for(lambda: app.query(ToolCard))
            assert await _wait_for(lambda: app.query_one(ToolCard).content)
            cards.extend(app.query(ToolCard))

    asyncio.run(go())
    assert cards[0].tool == "bash"
    assert "hi" in cards[0].content


def test_the_approval_is_asked_and_the_tool_runs(tmp_path):
    call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "bash", "arguments": '{"command": "echo hi"}'},
    }
    app = _app(
        tmp_path,
        responses=[
            {"role": "assistant", "content": "", "tool_calls": [call], "extra": {"cost": 0.0}},
            {"role": "assistant", "content": "done", "extra": {"cost": 0.0}},
        ],
        mode="default",
    )
    asked = []

    async def go():
        async with app.run_test() as pilot:
            await pilot.press(*"write it")
            await pilot.press("enter")
            assert await _wait_for(lambda: app.pending_approval is not None)
            asked.append(app.pending_approval.tool)
            await pilot.press("y")
            assert await _wait_for(lambda: app.pending_approval is None)

    asyncio.run(go())
    assert asked == ["bash"]


def test_the_approver_waits_for_the_answer(tmp_path):
    bus = EventBus()
    approver = TUIAprover(bus)
    seen = []
    bus.subscribe(EventType.APPROVAL_REQUEST, lambda event: seen.append(event.payload))
    results = []

    thread = threading.Thread(target=lambda: results.append(approver.request("bash", {"command": "ls"}, "why")))
    thread.start()
    for _ in range(200):
        if seen:
            break
        time.sleep(0.01)
    assert seen[0]["tool"] == "bash"
    approver.answer(seen[0]["id"], ApprovalDecision.ALLOW)
    thread.join(timeout=5)
    assert results[0] is ApprovalDecision.ALLOW
