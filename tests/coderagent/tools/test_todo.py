from coderagent.core.events import EventType
from coderagent.testing.factory import build_context
from coderagent.tools.builtin.todo import TodoWriteTool


def test_the_task_list_is_stored_in_the_session(tmp_path):
    ctx = build_context(tmp_path)
    result = TodoWriteTool().run(
        {
            "todos": [
                {"content": "read the code", "status": "completed"},
                {"content": "write the fix", "status": "pending"},
            ]
        },
        ctx,
    )
    assert "1/2 completed" in result.content
    assert ctx.session.metadata["todos"][1]["content"] == "write the fix"


def test_an_event_is_published_for_the_task_panel(tmp_path):
    ctx = build_context(tmp_path)
    seen: list[list] = []
    ctx.bus.subscribe(EventType.TOOL_RESULT, lambda event: seen.append(event.payload["todos"]))
    TodoWriteTool().run({"todos": [{"content": "one thing", "status": "in_progress"}]}, ctx)
    assert seen == [[{"content": "one thing", "status": "in_progress"}]]


def test_invalid_task_lists_are_rejected(tmp_path):
    ctx = build_context(tmp_path)
    assert TodoWriteTool().run({}, ctx).is_error
    assert TodoWriteTool().run({"todos": ["nope"]}, ctx).is_error
    assert TodoWriteTool().run({"todos": [{"content": "x", "status": "nope"}]}, ctx).is_error
    assert TodoWriteTool().run({"todos": [{"status": "pending"}]}, ctx).is_error
