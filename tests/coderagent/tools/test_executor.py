import json

from coderagent.core.events import EventType
from coderagent.testing.factory import AllowAllApprover, build_context, build_executor
from coderagent.tools.permissions import ApprovalDecision, PermissionMode
from coderagent.tools.rules import load_rules_file


class _DenyApprover:
    def request(self, tool: str, params: dict, reason: str) -> ApprovalDecision:
        return ApprovalDecision.DENY


class _AlwaysApprover:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, str]] = []

    def request(self, tool: str, params: dict, reason: str) -> ApprovalDecision:
        self.calls.append((tool, params, reason))
        return ApprovalDecision.ALWAYS


def _call(name: str, arguments: dict, call_id: str = "call_1") -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def test_plan_normalizes_the_tool_calls():
    executor = build_executor(".")
    actions = executor.plan([_call("read", {"path": "a.py"}, "call_9")])
    assert actions == [{"tool": "read", "tool_call_id": "call_9", "args": {"path": "a.py"}, "raw": actions[0]["raw"]}]


def test_plan_reports_broken_arguments():
    executor = build_executor(".")
    action = executor.plan([{"id": "c1", "function": {"name": "read", "arguments": "{not json"}}])[0]
    assert "could not parse" in action["error"]


def test_an_unknown_tool_is_reported_with_the_available_ones(tmp_path):
    executor = build_executor(tmp_path)
    observations = executor.execute(executor.plan([_call("teleport", {})]))
    assert "unknown tool 'teleport'" in observations[0]["content"]
    assert "read" in observations[0]["content"]


def test_broken_arguments_become_an_observation(tmp_path):
    executor = build_executor(tmp_path)
    action = {"id": "c1", "function": {"name": "read", "arguments": "{not json}"}}
    assert "could not parse" in executor.execute(executor.plan([action]))[0]["content"]


def test_a_denied_tool_is_not_run(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("original\n", encoding="utf-8")
    executor = build_executor(tmp_path, mode=PermissionMode.DEFAULT, approver=_DenyApprover())
    observations = executor.execute(executor.plan([_call("write", {"path": "a.py", "content": "new"})]))
    assert "denied" in observations[0]["content"]
    assert target.read_text(encoding="utf-8") == "original\n"


def test_an_approved_tool_is_run(tmp_path):
    target = tmp_path / "a.py"
    executor = build_executor(tmp_path, mode=PermissionMode.DEFAULT, approver=AllowAllApprover())
    observations = executor.execute(executor.plan([_call("write", {"path": "a.py", "content": "new\n"})]))
    assert observations[0]["content"].startswith("Created")
    assert target.read_text(encoding="utf-8") == "new\n"


def test_an_always_decision_is_written_to_the_user_rule_file(tmp_path):
    home = tmp_path / "home"
    executor = build_executor(tmp_path, mode=PermissionMode.DEFAULT, approver=_AlwaysApprover(), rules_home=home)
    executor.execute(executor.plan([_call("write", {"path": "a.py", "content": "x"})]))
    rules = load_rules_file(home / "rules.yaml")
    assert [(rule.tool, rule.decision) for rule in rules] == [("write", "allow")]


def test_parallel_results_keep_the_order_of_the_tool_calls(tmp_path):
    executor = build_executor(tmp_path)
    calls = [
        _call("read", {"path": "a.py"}, "first"),
        _call("read", {"path": "b.py"}, "second"),
        _call("read", {"path": "c.py"}, "third"),
    ]
    (tmp_path / "a.py").write_text("AAA\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("BBB\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("CCC\n", encoding="utf-8")
    observations = executor.execute(executor.plan(calls))
    assert [observation["tool_call_id"] for observation in observations] == ["first", "second", "third"]
    assert [observation["content"] for observation in observations] == ["1\tAAA", "1\tBBB", "1\tCCC"]


def test_a_write_call_makes_the_whole_batch_sequential(tmp_path):
    (tmp_path / "a.py").write_text("AAA\n", encoding="utf-8")
    executor = build_executor(tmp_path)
    calls = [_call("read", {"path": "a.py"}, "read"), _call("write", {"path": "b.py", "content": "x"}, "write")]
    observations = executor.execute(executor.plan(calls))
    assert [observation["tool_call_id"] for observation in observations] == ["read", "write"]


def test_a_failing_tool_does_not_stop_the_other_calls(tmp_path):
    executor = build_executor(tmp_path)
    calls = [_call("read", {"path": "missing.py"}, "missing"), _call("read", {"path": "a.py"}, "ok")]
    (tmp_path / "a.py").write_text("AAA\n", encoding="utf-8")
    observations = executor.execute(executor.plan(calls))
    assert observations[0]["content"].startswith("Error:")
    assert observations[1]["content"] == "1\tAAA"


def test_the_executor_publishes_the_tool_results(tmp_path):
    ctx = build_context(tmp_path)
    seen: list[str] = []
    ctx.bus.subscribe(EventType.TOOL_RESULT, lambda event: seen.append(event.payload["tool"]))
    executor = build_executor(tmp_path, context=ctx)
    executor.execute(executor.plan([_call("read", {"path": "a.py"})]))
    assert seen == ["read"]


def test_a_secret_in_the_output_of_a_tool_is_hidden(tmp_path):
    (tmp_path / "a.env").write_text("API_KEY=sk-abcdefghijklmnopqrstuvwxyz\n", encoding="utf-8")
    executor = build_executor(tmp_path)
    observations = executor.execute(executor.plan([_call("read", {"path": "a.env"})]))
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in observations[0]["content"]
    assert "[redacted]" in observations[0]["content"]


def test_a_secret_does_not_reach_the_log_of_the_session(tmp_path):
    from coderagent.core.session import SessionStore

    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    (tmp_path / "a.env").write_text("API_KEY=sk-abcdefghijklmnopqrstuvwxyz\n", encoding="utf-8")
    executor = build_executor(tmp_path, store=store, context=build_context(tmp_path, session=session))
    executor.execute(executor.plan([_call("read", {"path": "a.env"})]))
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in store.path(session.id).read_text(encoding="utf-8")
