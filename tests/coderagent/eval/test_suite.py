"""The tests of the suites that ship with the harness."""

import subprocess
from pathlib import Path

import pytest

from coderagent.config.loader import load_config
from coderagent.core.session import SessionStore
from coderagent.eval.runner import prepare_workdir, run_suite
from coderagent.eval.task import load_suite, task_overrides, task_permission_mode
from coderagent.tools.permissions import PermissionPolicy, Rule

SUITE = Path(__file__).parents[3] / "evals" / "basic"
IDS = [
    "cli-flag",
    "config-value",
    "create-file",
    "grep-count",
    "import-error",
    "long-conversation",
    "no-op",
    "off-by-one",
    "rename-symbol",
]
"""The tasks of the suite, in the order they are sorted."""

OFFLINE = Path(__file__).parents[3] / "evals" / "offline"
OFFLINE_IDS = ["bash-command", "broken-check", "edit-file", "multi-turn", "read-only", "write-file"]
"""The tasks of the suite that needs no API key."""


def test_the_suite_holds_the_tasks_it_should():
    assert [task.id for task in load_suite(SUITE)] == IDS


@pytest.mark.parametrize("task_id", [task_id for task_id in IDS if task_id != "no-op"])
def test_a_task_is_not_solved_before_the_agent_starts(task_id, tmp_path):
    """Otherwise the agent would pass by doing nothing."""
    task = next(task for task in load_suite(SUITE) if task.id == task_id)
    workdir = prepare_workdir(task, tmp_path / task_id)
    results = [subprocess.run(command, shell=True, cwd=workdir) for command in task.verify]
    assert any(result.returncode != 0 for result in results)


def test_the_no_op_task_is_satisfied_from_the_start(tmp_path):
    """Its check passes before the agent does anything: the agent must not break what is fine."""
    task = next(task for task in load_suite(SUITE) if task.id == "no-op")
    workdir = prepare_workdir(task, tmp_path / "no-op")
    results = [subprocess.run(command, shell=True, cwd=workdir) for command in task.verify]
    assert all(result.returncode == 0 for result in results)


def _policy(task, cwd: Path) -> PermissionPolicy:
    """The policy of a task: its own mode and its own rules."""
    rules = [
        Rule(**{key: value for key, value in rule.items() if key in ("tool", "pattern", "decision", "reason")})
        for override in task_overrides(task)
        for rule in (override.get("permissions") or {}).get("rules") or []
    ]
    return PermissionPolicy(task_permission_mode(task) or "default", rules, cwd=cwd)


def test_the_tasks_that_may_only_be_edited_cannot_be_rewritten(tmp_path):
    """A broken edit must not be routed around: the file may only change with the edit tool."""
    checked = 0
    for task in load_suite(SUITE):
        policy = _policy(task, tmp_path)
        for rule in policy.rules:
            if rule.tool not in ("write", "multi_edit"):
                continue
            checked += 1
            assert policy.mode.value == "default", "the rules of bash only count outside of bypass"
            assert policy.evaluate("write", {"path": rule.pattern}).decision == "deny"
            assert policy.evaluate("multi_edit", {"path": rule.pattern}).decision == "deny"
            for command in [
                f"printf x > {rule.pattern}",
                f"cat <<EOF > {rule.pattern}",
                f"sed -i s/a/b/ {rule.pattern}",
                f"cp other.py {rule.pattern}",
                f"tee {rule.pattern}",
                f"python3 - <<'EOF'\np='{rule.pattern}'\nopen(p,'w').write('x')\nEOF",
                f"python3 -c \"open('{rule.pattern}','w').write('x')\"",
            ]:
                assert policy.evaluate("bash", {"command": command}).decision == "deny", command
            for command in [f"cat {rule.pattern}", f"python {rule.pattern}"]:
                assert policy.evaluate("bash", {"command": command}).decision != "deny", command
    assert checked, "the suite has no task that protects a file"


def test_the_tasks_that_need_the_edit_tool_say_so(tmp_path):
    """A task that may only be edited needs the edit tool, or the suite cannot see a broken one."""
    needing = {task.id: task for task in load_suite(SUITE) if task.require_tools}
    assert set(needing) == {"cli-flag", "config-value", "import-error", "off-by-one", "rename-symbol"}
    for task in needing.values():
        assert [requirement.tools for requirement in task.require_tools] == [["edit", "multi_edit"]]
        assert all(requirement.paths for requirement in task.require_tools), "the file of the task matters"
        protected = {
            rule["pattern"]
            for override in task_overrides(task)
            for rule in (override.get("permissions") or {}).get("rules") or []
            if rule["tool"] == "write"
        }
        assert set(task.require_tools[0].paths) == protected


def test_the_offline_suite_needs_no_api_key(tmp_path):
    """Every task of it is scripted, so the run never calls a model."""
    assert [task.id for task in load_suite(OFFLINE)] == OFFLINE_IDS
    assert all(task.script for task in load_suite(OFFLINE))


def test_the_offline_suite_does_what_it_should(tmp_path):
    """The harness works, and the check of the suite is able to fail."""
    config = load_config([], cwd=tmp_path)
    store = SessionStore(tmp_path / "home" / "sessions")
    results = run_suite(
        load_suite(OFFLINE),
        config,
        root=tmp_path / "work",
        store=store,
        user_home=tmp_path / "home",
    )
    assert [result.id for result in results] == OFFLINE_IDS
    assert all(result.as_expected for result in results)
    assert [result.id for result in results if result.passed] == [
        "bash-command",
        "edit-file",
        "multi-turn",
        "read-only",
        "write-file",
    ]
